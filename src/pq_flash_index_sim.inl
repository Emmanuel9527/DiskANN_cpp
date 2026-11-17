// N2: event-driven simulation of concurrent searches (included by pq_flash_index.cpp before the instantiations).
// Functional part = the original unfiltered L2 beam search of cached_beam_search; timing = simulated SSD + host
// profile. With policy.nominate == 0 the visited nodes and results equal cached_beam_search (same L, W, cache).
// Node cache (load_cache_list before the call): a cached nominee takes one of the W slots like in
// cached_beam_search, is always "free" for the SSD choice, is never read or prefetched, and is expanded from the
// cache. A round whose chosen nodes are all cached issues no read and costs no simulated time: the measured host
// profiles (build_closed_loop_schedule.py) fold such rounds into the gap before the next round that reads.

template <typename T, typename LabelT>
void PQFlashIndex<T, LabelT>::simulate_search(const T *queries, uint64_t num_queries, uint64_t query_aligned_dim,
                                              uint64_t k_search, uint64_t l_search, uint64_t beam_width,
                                              uint32_t workers, const SimHostProfile &host,
                                              const SimSSDParams &ssd, const SimPolicy &policy, uint64_t seed,
                                              uint64_t *res_ids, float *res_dists,
                                              std::vector<SimQueryResult> &per_query, SimSummary &summary)
{
    if (metric != diskann::Metric::L2 || _use_disk_index_pq)
        throw ANNException("simulate_search supports L2 without disk PQ", -1, __FUNCSIG__, __FILE__, __LINE__);
    if (policy.nominate > 0 && policy.nominate < beam_width)
        throw ANNException("nominate must be 0 or >= beam_width", -1, __FUNCSIG__, __FILE__, __LINE__);
    if (host.gap_us.empty() || host.first_gap_us.empty())
        throw ANNException("host profile has no gap samples", -1, __FUNCSIG__, __FILE__, __LINE__);
    workers = (uint32_t)(std::min<uint64_t>)(workers, num_queries);

    ScratchStoreManager<SSDThreadData<T>> manager(this->_thread_data);
    auto tdata = manager.scratch_space();
    IOContext &ctx = tdata->ctx;
    const uint64_t num_sectors_per_node = _nnodes_per_sector > 0 ? 1 : DIV_ROUND_UP(_max_node_len, defaults::SECTOR_LEN);
    const uint64_t node_bytes = num_sectors_per_node * defaults::SECTOR_LEN;
    const uint64_t max_reads = (std::max<uint64_t>)(beam_width, policy.nominate);
    char *sector_buf = nullptr;
    alloc_aligned((void **)&sector_buf, max_reads * node_bytes, defaults::SECTOR_LEN);
    T *coord_buf = nullptr;
    alloc_aligned((void **)&coord_buf, _aligned_dim * sizeof(T), 8 * sizeof(T));
    memset(coord_buf, 0, _aligned_dim * sizeof(T));
    std::vector<uint8_t> pq_coord_scratch((_max_degree + 1) * _n_chunks);
    std::vector<float> dist_scratch(_max_degree + 1);
    const double service_us = ssd.cmd_us + ssd.tr_us + ssd.xfer_us;
    std::mt19937_64 rng(seed);
    auto sample = [&](const std::vector<double> &v) { return v[std::uniform_int_distribution<size_t>(0, v.size() - 1)(rng)]; };
    auto unit_of = [&](uint64_t sector) { return (uint32_t)((sector / ssd.sectors_per_page) % ssd.units); };

    // ---------------- per-worker search state ----------------
    struct Node
    {
        uint32_t id;
        std::vector<T> coords;
        std::vector<uint32_t> nbrs;
    };
    struct Worker
    {
        int64_t query = -1;
        NeighborPriorityQueue retset;
        tsl::robin_set<uint64_t> visited;
        std::vector<Neighbor> full;
        T *q_T = nullptr;
        float *q_float = nullptr, *q_rot = nullptr, *pq_dists = nullptr;
        std::vector<size_t> nominee_pos;
        std::vector<Node> round_nodes;
        uint32_t outstanding = 0;
        double round_first_arrival = 0;
    };
    std::vector<Worker> ws(workers);
    for (auto &w : ws)
    {
        w.retset.reserve(l_search);
        alloc_aligned((void **)&w.q_T, _aligned_dim * sizeof(T), 8 * sizeof(T));
        alloc_aligned((void **)&w.q_float, _aligned_dim * sizeof(float), 32);
        alloc_aligned((void **)&w.q_rot, _aligned_dim * sizeof(float), 32);
        alloc_aligned((void **)&w.pq_dists, 256 * _n_chunks * sizeof(float), 32);
    }
    per_query.assign(num_queries, SimQueryResult());
    summary = SimSummary();

    auto compute_dists = [&](Worker &w, const uint32_t *ids, uint64_t n, float *out) {
        diskann::aggregate_coords(ids, n, this->data, this->_n_chunks, pq_coord_scratch.data());
        diskann::pq_dist_lookup(pq_coord_scratch.data(), n, this->_n_chunks, w.pq_dists, out);
    };
    auto read_nodes = [&](const std::vector<uint32_t> &ids, std::vector<Node> &out) {
        std::vector<AlignedRead> reqs;
        for (size_t i = 0; i < ids.size(); i++)
            reqs.emplace_back(get_node_sector(ids[i]) * defaults::SECTOR_LEN, node_bytes, sector_buf + i * node_bytes);
        reader->read(reqs, ctx);
        for (size_t i = 0; i < ids.size(); i++)
        {
            char *node_disk_buf = offset_to_node(sector_buf + i * node_bytes, ids[i]);
            uint32_t *nb = offset_to_node_nhood(node_disk_buf);
            T *c = offset_to_node_coords(node_disk_buf);
            Node nd;
            nd.id = ids[i];
            nd.coords.assign(c, c + _data_dim);
            nd.nbrs.assign(nb + 1, nb + 1 + *nb);
            out.push_back(std::move(nd));
        }
    };
    auto cached_node = [&](uint32_t id, std::vector<Node> &out) {
        const auto nh = _nhood_cache.find(id)->second;
        const T *c = _coord_cache.find(id)->second;
        Node nd;
        nd.id = id;
        nd.coords.assign(c, c + _data_dim);
        nd.nbrs.assign(nh.second, nh.second + nh.first);
        out.push_back(std::move(nd));
    };
    auto start_query = [&](Worker &w, int64_t q) {
        w.query = q;
        w.retset.clear();
        w.visited.clear();
        w.full.clear();
        const T *src = queries + q * query_aligned_dim;
        memset(w.q_T, 0, _aligned_dim * sizeof(T));
        memset(w.q_float, 0, _aligned_dim * sizeof(float));
        memset(w.q_rot, 0, _aligned_dim * sizeof(float));
        for (size_t d = 0; d < _data_dim; d++)
        {
            w.q_T[d] = src[d];
            w.q_float[d] = w.q_rot[d] = (float)src[d];
        }
        _pq_table.preprocess_query(w.q_rot);
        _pq_table.populate_chunk_distances(w.q_rot, w.pq_dists);
        uint32_t best_medoid = 0;
        float best_dist = (std::numeric_limits<float>::max)();
        for (uint64_t m = 0; m < _num_medoids; m++)
        {
            float d = _dist_cmp_float->compare(w.q_float, _centroid_data + _aligned_dim * m, (uint32_t)_aligned_dim);
            if (d < best_dist)
            {
                best_medoid = _medoids[m];
                best_dist = d;
            }
        }
        float d0;
        compute_dists(w, &best_medoid, 1, &d0);
        w.retset.insert(Neighbor(best_medoid, d0));
        w.visited.insert(best_medoid);
    };
    auto expand_round = [&](Worker &w) {
        for (auto &nd : w.round_nodes)
        {
            memcpy(coord_buf, nd.coords.data(), _data_dim * sizeof(T));
            w.full.push_back(Neighbor(nd.id, _dist_cmp->compare(w.q_T, coord_buf, (uint32_t)_aligned_dim)));
            compute_dists(w, nd.nbrs.data(), nd.nbrs.size(), dist_scratch.data());
            for (size_t m = 0; m < nd.nbrs.size(); m++)
            {
                uint32_t id = nd.nbrs[m];
                if (w.visited.insert(id).second)
                {
                    if (_dummy_pts.find(id) != _dummy_pts.end())
                        continue;
                    w.retset.insert(Neighbor(id, dist_scratch[m]));
                }
            }
        }
        w.round_nodes.clear();
    };
    // host side of a round: the k top unexpanded candidates (k = W for the original beam)
    auto nominate = [&](Worker &w) {
        w.nominee_pos.clear();
        const uint32_t k = policy.nominate > 0 ? policy.nominate : (uint32_t)beam_width;
        for (size_t pos = 0; pos < w.retset.size() && w.nominee_pos.size() < k; pos++)
            if (!w.retset[pos].expanded)
                w.nominee_pos.push_back(pos);
    };
    auto finish_query = [&](Worker &w) {
        std::sort(w.full.begin(), w.full.end());
        for (uint64_t i = 0; i < k_search; i++)
        {
            uint64_t id = i < w.full.size() ? w.full[i].id : 0;
            if (_dummy_pts.find((uint32_t)id) != _dummy_pts.end())
                id = _dummy_to_real_map[(uint32_t)id];
            res_ids[w.query * k_search + i] = id;
            if (res_dists)
                res_dists[w.query * k_search + i] = i < w.full.size() ? w.full[i].distance : 0;
        }
    };

    // ---------------- SSD model ----------------
    struct Read
    {
        uint32_t worker;
        uint64_t sector;
        uint32_t unit;
        bool prefetch;
        uint8_t state; // 0 queued, 1 in service, 2 done
        double arrive, start;
        std::vector<uint32_t> waiters; // workers whose critical read attached to this prefetch
    };
    struct Unit
    {
        bool busy = false;
        uint32_t current = 0;
        double current_start = 0;
        std::deque<uint32_t> hi, lo;
    };
    std::vector<Read> reads;
    std::vector<Unit> units(ssd.units);
    std::vector<double> chan_free(ssd.channels, 0.0);
    double host_if_free = 0.0;
    // completion of a host read whose data is ready at t_ready: shared host interface, then the fixed path latency
    auto host_complete = [&](double t_ready) {
        const double s = (std::max)(t_ready, host_if_free);
        host_if_free = s + ssd.host_xfer_us;
        return s + ssd.host_xfer_us + ssd.iface_us;
    };
    std::list<uint64_t> buf_lru;
    tsl::robin_map<uint64_t, std::list<uint64_t>::iterator> buf_pos;
    tsl::robin_map<uint64_t, uint32_t> inflight_prefetch; // sector -> read id

    enum EvType : uint8_t
    {
        QUERY_START,
        ROUND_START,
        SSD_CHOOSE,
        ARRIVE,
        SENSE_DONE,
        XFER_DONE,
        COMPLETE,
        PROCESS
    };
    struct Ev
    {
        double t;
        uint64_t seq;
        EvType type;
        uint32_t a;
        bool operator>(const Ev &o) const
        {
            return t > o.t || (t == o.t && seq > o.seq);
        }
    };
    std::priority_queue<Ev, std::vector<Ev>, std::greater<Ev>> evq;
    uint64_t seq = 0;
    auto push = [&](double t, EvType ty, uint32_t a) { evq.push(Ev{t, seq++, ty, a}); };

    auto try_start = [&](uint32_t u, double t) {
        Unit &U = units[u];
        if (U.busy)
            return;
        uint32_t r;
        if (!U.hi.empty())
        {
            r = U.hi.front();
            U.hi.pop_front();
        }
        else if (!U.lo.empty())
        {
            r = U.lo.front();
            U.lo.pop_front();
        }
        else
            return;
        U.busy = true;
        U.current = r;
        U.current_start = t;
        reads[r].state = 1;
        reads[r].start = t;
        if (!reads[r].prefetch)
            summary.read_wait_us.push_back((float)(t - reads[r].arrive));
        push(t + ssd.cmd_us + ssd.tr_us, SENSE_DONE, r);
    };
    auto buffer_has = [&](uint64_t s) { return buf_pos.find(s) != buf_pos.end(); };
    auto buffer_insert = [&](uint64_t s) {
        auto it = buf_pos.find(s);
        if (it != buf_pos.end())
        {
            buf_lru.splice(buf_lru.begin(), buf_lru, it->second);
            return;
        }
        buf_lru.push_front(s);
        buf_pos[s] = buf_lru.begin();
        if (buf_lru.size() > policy.prefetch_buffer)
        {
            buf_pos.erase(buf_lru.back());
            buf_lru.pop_back();
        }
    };
    auto buffer_touch = [&](uint64_t s) {
        auto it = buf_pos.find(s);
        if (it != buf_pos.end())
            buf_lru.splice(buf_lru.begin(), buf_lru, it->second);
    };
    auto new_read = [&](uint32_t worker, uint64_t sector, bool prefetch, double t) {
        Read r;
        r.worker = worker;
        r.sector = sector;
        r.unit = unit_of(sector);
        r.prefetch = prefetch;
        r.state = 0;
        r.arrive = t;
        r.start = 0;
        reads.push_back(std::move(r));
        return (uint32_t)(reads.size() - 1);
    };
    // estimated wait (us) before a new critical read on unit u would start, plus already-chosen reads this round
    auto est_wait = [&](uint32_t u, double t, uint32_t extra) {
        const Unit &U = units[u];
        double w = 0;
        if (U.busy)
            w += (std::max)(0.0, U.current_start + service_us - t);
        w += (U.hi.size() + extra) * service_us;
        return w;
    };

    // ---------------- events ----------------
    int64_t next_query = 0;
    for (uint32_t i = 0; i < workers; i++)
        push(0.0, QUERY_START, i);
    std::vector<uint32_t> chosen_ids;
    std::vector<uint64_t> chosen_secs;
    while (!evq.empty())
    {
        const Ev ev = evq.top();
        evq.pop();
        const double t = ev.t;
        switch (ev.type)
        {
        case QUERY_START: {
            Worker &w = ws[ev.a];
            if (next_query >= (int64_t)num_queries)
                break;
            const int64_t q = next_query++;
            start_query(w, q);
            per_query[q].start_us = t;
            per_query[q].worker = ev.a;
            push(t + sample(host.first_gap_us), ROUND_START, ev.a);
            break;
        }
        case ROUND_START: {
            nominate(ws[ev.a]);
            push(t + host.pre_us, SSD_CHOOSE, ev.a);
            break;
        }
        case SSD_CHOOSE: {
            Worker &w = ws[ev.a];
            // A round served entirely from the node cache is expanded at once and the next round is chosen at the
            // same instant (no pre time: the measured profile has none for rounds without reads).
            for (;;)
            {
                const size_t n = w.nominee_pos.size();
                std::vector<char> chosen(n, 0), cached(n, 0);
                std::vector<uint64_t> sec(n);
                std::vector<uint32_t> extra(ssd.units, 0);
                for (size_t j = 0; j < n; j++)
                {
                    const uint32_t id = w.retset[w.nominee_pos[j]].id;
                    sec[j] = get_node_sector(id);
                    cached[j] = !_nhood_cache.empty() && _nhood_cache.find(id) != _nhood_cache.end();
                }
                uint32_t picked = 0;
                if (policy.nominate == 0 || !policy.avoid_busy)
                {
                    for (size_t j = 0; j < n && picked < beam_width; j++)
                        chosen[j] = 1, picked++;
                }
                else
                {
                    for (int pass = 0; pass < 2 && picked < beam_width; pass++)
                        for (size_t j = 0; j < n && picked < beam_width; j++)
                        {
                            if (chosen[j])
                                continue;
                            const uint32_t u = unit_of(sec[j]);
                            if (pass == 0 && !cached[j] && !buffer_has(sec[j]) &&
                                est_wait(u, t, extra[u]) > policy.wait_threshold_us)
                                continue;
                            chosen[j] = 1;
                            picked++;
                            if (!cached[j] && !buffer_has(sec[j]))
                                extra[u]++;
                        }
                }
                chosen_ids.clear();
                chosen_secs.clear();
                for (size_t j = 0; j < n; j++)
                    if (chosen[j])
                    {
                        w.retset.mark_expanded(w.nominee_pos[j]);
                        const uint32_t id = w.retset[w.nominee_pos[j]].id;
                        if (cached[j])
                        {
                            cached_node(id, w.round_nodes);
                            per_query[w.query].cache_hits++;
                            summary.cache_hits++;
                            continue;
                        }
                        chosen_ids.push_back(id);
                        chosen_secs.push_back(sec[j]);
                    }
                if (!chosen_ids.empty())
                {
                    read_nodes(chosen_ids, w.round_nodes); // functional contents; timing below
                    per_query[w.query].rounds++;
                    per_query[w.query].reads += (uint32_t)chosen_ids.size();
                    w.outstanding = (uint32_t)chosen_ids.size();
                    w.round_first_arrival = t;
                    for (size_t i = 0; i < chosen_secs.size(); i++)
                        push(t + host.spacing_us * i, ARRIVE,
                             new_read(ev.a, chosen_secs[i], false, t + host.spacing_us * i));
                    if (policy.prefetch_buffer > 0)
                        for (size_t j = 0; j < n; j++)
                            if (!chosen[j] && !cached[j])
                                push(t + host.spacing_us * chosen_secs.size(), ARRIVE,
                                     new_read(ev.a, sec[j], true, t + host.spacing_us * chosen_secs.size()));
                    break;
                }
                summary.cache_only_rounds++;
                expand_round(w);
                if (!w.retset.has_unexpanded_node())
                {
                    finish_query(w);
                    per_query[w.query].end_us = t;
                    summary.end_us = (std::max)(summary.end_us, t);
                    push(t, QUERY_START, ev.a);
                    break;
                }
                nominate(w);
            }
            break;
        }
        case ARRIVE: {
            const uint32_t r = ev.a;
            Read &R = reads[r];
            if (R.prefetch)
            {
                if (buffer_has(R.sector) || inflight_prefetch.count(R.sector) ||
                    units[R.unit].lo.size() >= policy.prefetch_queue_limit)
                {
                    summary.prefetch_dropped++;
                    R.state = 2;
                    break;
                }
                summary.prefetch_issued++;
                inflight_prefetch[R.sector] = r;
                units[R.unit].lo.push_back(r);
                try_start(R.unit, t);
                break;
            }
            summary.critical_reads++;
            if (policy.prefetch_buffer > 0 && buffer_has(R.sector))
            {
                buffer_touch(R.sector);
                summary.buffer_hits++;
                per_query[ws[R.worker].query].buffer_hits++;
                R.state = 2;
                const double tc = host_complete(t + ssd.hit_us - ssd.iface_us);
                summary.read_latency_us.push_back((float)(tc - t));
                push(tc, COMPLETE, R.worker);
                break;
            }
            auto pit = inflight_prefetch.find(R.sector);
            if (pit != inflight_prefetch.end())
            {
                Read &P = reads[pit->second];
                P.waiters.push_back(R.worker);
                summary.prefetch_waits++;
                per_query[ws[R.worker].query].prefetch_waits++;
                if (P.state == 0)
                { // still queued at low priority: promote (once)
                    auto &lo = units[P.unit].lo;
                    auto it = std::find(lo.begin(), lo.end(), pit->second);
                    if (it != lo.end())
                    {
                        lo.erase(it);
                        units[P.unit].hi.push_back(pit->second);
                        summary.prefetch_promoted++;
                    }
                }
                R.state = 2;
                R.start = t; // latency of attached reads is recorded at the prefetch completion
                break;
            }
            summary.flash_reads++;
            units[R.unit].hi.push_back(r);
            try_start(R.unit, t);
            break;
        }
        case SENSE_DONE: {
            Read &R = reads[ev.a];
            const uint32_t c = R.unit % ssd.channels;
            const double xs = (std::max)(t, chan_free[c]);
            chan_free[c] = xs + ssd.xfer_us;
            push(xs + ssd.xfer_us, XFER_DONE, ev.a);
            break;
        }
        case XFER_DONE: {
            const uint32_t r = ev.a;
            Read &R = reads[r];
            R.state = 2;
            Unit &U = units[R.unit];
            U.busy = false;
            summary.unit_busy_us += t - R.start;
            if (R.prefetch)
            {
                summary.prefetch_completed++;
                inflight_prefetch.erase(R.sector);
                buffer_insert(R.sector);
                for (uint32_t wk : R.waiters)
                {
                    const double tc = host_complete(t);
                    summary.read_latency_us.push_back((float)(tc - R.arrive));
                    push(tc, COMPLETE, wk);
                }
            }
            else
            {
                const double tc = host_complete(t);
                summary.read_latency_us.push_back((float)(tc - R.arrive));
                push(tc, COMPLETE, R.worker);
            }
            try_start(R.unit, t);
            break;
        }
        case COMPLETE: {
            Worker &w = ws[ev.a];
            if (--w.outstanding == 0)
            {
                summary.round_us.push_back((float)(t - w.round_first_arrival));
                push(t + host.post_us, PROCESS, ev.a);
            }
            break;
        }
        case PROCESS: {
            Worker &w = ws[ev.a];
            expand_round(w);
            if (w.retset.has_unexpanded_node())
                push(t + sample(host.gap_us), ROUND_START, ev.a);
            else
            {
                finish_query(w);
                per_query[w.query].end_us = t;
                summary.end_us = (std::max)(summary.end_us, t);
                push(t, QUERY_START, ev.a);
            }
            break;
        }
        }
    }
    for (auto &w : ws)
    {
        aligned_free(w.q_T);
        aligned_free(w.q_float);
        aligned_free(w.q_rot);
        aligned_free(w.pq_dists);
    }
    aligned_free(sector_buf);
    aligned_free(coord_buf);
}
