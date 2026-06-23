# DiskANN

[![DiskANN Main](https://github.com/microsoft/DiskANN/actions/workflows/push-test.yml/badge.svg?branch=main)](https://github.com/microsoft/DiskANN/actions/workflows/push-test.yml)
[![PyPI version](https://img.shields.io/pypi/v/diskannpy.svg)](https://pypi.org/project/diskannpy/)
[![Downloads shield](https://pepy.tech/badge/diskannpy)](https://pepy.tech/project/diskannpy)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[![DiskANN Paper](https://img.shields.io/badge/Paper-NeurIPS%3A_DiskANN-blue)](https://papers.nips.cc/paper/9527-rand-nsg-fast-accurate-billion-point-nearest-neighbor-search-on-a-single-node.pdf)
[![DiskANN Paper](https://img.shields.io/badge/Paper-Arxiv%3A_Fresh--DiskANN-blue)](https://arxiv.org/abs/2105.09613)
[![DiskANN Paper](https://img.shields.io/badge/Paper-Filtered--DiskANN-blue)](https://harsha-simhadri.org/pubs/Filtered-DiskANN23.pdf)


DiskANN is a suite of scalable, accurate and cost-effective approximate nearest neighbor search algorithms for large-scale vector search that support real-time changes and simple filters.
This code is based on ideas from the [DiskANN](https://papers.nips.cc/paper/9527-rand-nsg-fast-accurate-billion-point-nearest-neighbor-search-on-a-single-node.pdf), [Fresh-DiskANN](https://arxiv.org/abs/2105.09613) and the [Filtered-DiskANN](https://harsha-simhadri.org/pubs/Filtered-DiskANN23.pdf) papers with further improvements. 
This code forked off from [code for NSG](https://github.com/ZJULearning/nsg) algorithm.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

See [guidelines](CONTRIBUTING.md) for contributing to this project.

## Linux build:

Install the following packages through apt-get

```bash
sudo apt install make cmake g++ libaio-dev libgoogle-perftools-dev clang-format libboost-all-dev
```

### Install Intel MKL
#### Ubuntu 20.04 or newer
```bash
sudo apt install libmkl-full-dev
```

#### Earlier versions of Ubuntu
Install Intel MKL either by downloading the [oneAPI MKL installer](https://www.intel.com/content/www/us/en/developer/tools/oneapi/onemkl.html) or using [apt](https://software.intel.com/en-us/articles/installing-intel-free-libs-and-python-apt-repo) (we tested with build 2019.4-070 and 2022.1.2.146).

```
# OneAPI MKL Installer
wget https://registrationcenter-download.intel.com/akdlm/irc_nas/18487/l_BaseKit_p_2022.1.2.146.sh
sudo sh l_BaseKit_p_2022.1.2.146.sh -a --components intel.oneapi.lin.mkl.devel --action install --eula accept -s
```

### Build
```bash
mkdir build && cd build && cmake -DCMAKE_BUILD_TYPE=Release .. && make -j 
```

## Windows build:

The Windows version has been tested with Enterprise editions of Visual Studio 2022, 2019 and 2017. It should work with the Community and Professional editions as well without any changes. 

**Prerequisites:**

* CMake 3.15+ (available in VisualStudio 2019+ or from https://cmake.org)
* NuGet.exe (install from https://www.nuget.org/downloads)
    * The build script will use NuGet to get MKL, OpenMP and Boost packages.
* DiskANN git repository checked out together with submodules. To check out submodules after git clone:
```
git submodule init
git submodule update
```

* Environment variables: 
    * [optional] If you would like to override the Boost library listed in windows/packages.config.in, set BOOST_ROOT to your Boost folder.

**Build steps:**
* Open the "x64 Native Tools Command Prompt for VS 2019" (or corresponding version) and change to DiskANN folder
* Create a "build" directory inside it
* Change to the "build" directory and run
```
cmake ..
```
OR for Visual Studio 2017 and earlier:
```
<full-path-to-installed-cmake>\cmake ..
```
**This will create a diskann.sln solution**. Now you can:

- Open it from VisualStudio and build either Release or Debug configuration.
- `<full-path-to-installed-cmake>\cmake --build build`
- Use MSBuild:
```
msbuild.exe diskann.sln /m /nologo /t:Build /p:Configuration="Release" /property:Platform="x64"
```

* This will also build gperftools submodule for libtcmalloc_minimal dependency.
* Generated binaries are stored in the x64/Release or x64/Debug directories.

## Usage:

Please see the following pages on using the compiled code:

- [Commandline interface for building and search SSD based indices](workflows/SSD_index.md)  
- [Commandline interface for building and search in memory indices](workflows/in_memory_index.md) 
- [Commandline examples for using in-memory streaming indices](workflows/dynamic_index.md)
- [Commandline interface for building and search in memory indices with label data and filters](workflows/filtered_in_memory.md)
- [Commandline interface for building and search SSD based indices with label data and filters](workflows/filtered_ssd_index.md)
- [diskannpy - DiskANN as a python extension module](python/README.md)

Please cite this software in your work as:

```
@misc{diskann-github,
   author = {Simhadri, Harsha Vardhan and Krishnaswamy, Ravishankar and Srinivasa, Gopal and Subramanya, Suhas Jayaram and Antonijevic, Andrija and Pryce, Dax and Kaczynski, David and Williams, Shane and Gollapudi, Siddarth and Sivashankar, Varun and Karia, Neel and Singh, Aditi and Jaiswal, Shikhar and Mahapatro, Neelam and Adams, Philip and Tower, Bryan and Patel, Yash}},
   title = {{DiskANN: Graph-structured Indices for Scalable, Fast, Fresh and Filtered Approximate Nearest Neighbor Search}},
   url = {https://github.com/Microsoft/DiskANN},
   version = {0.6.1},
   year = {2023}
}
```

## Block-Shuffled Disk Layout Extensions

For the complete build and three-way experiment commands, see
[Block-Shuffled Disk Layout Experiment](workflows/block_shuffled_disk_layout.md).

This fork adds an experimental disk-layout path for studying whether graph-local
points can be packed into the same disk sector and then exploited during
disk-based beam search.

### What changed compared with upstream DiskANN

- `apps/utils/create_disk_layout` accepts a `block_shuffle` layout mode.
- `src/disk_utils.cpp` contains block-shuffling logic that groups graph-near
  nodes into the same fixed-size disk block when multiple nodes fit in one
  4KB sector.
- Block-shuffled layout generation renumbers nodes and rewrites graph neighbor
  ids from old ids to new ids.
- The layout writer emits:
  - `<disk_index>_block_shuffle_old_to_new.bin`
  - `<disk_index>_block_shuffle_new_to_old.bin`
- `apps/search_disk_index` accepts `--result_new_to_old_map` so recall can be
  computed against ground truth in the original id space.
- `apps/search_disk_index` accepts `--use_sector_candidates` to enable a new
  sector-aware search mode. In this mode, when beam search reads the sector for
  a frontier node, it also expands the other valid nodes already present in the
  same sector. This is intended to turn block-shuffled physical locality into
  useful search-time candidates.

By default, `search_disk_index` keeps the upstream node-centric behavior. The
new sector-aware behavior is enabled only when `--use_sector_candidates` is
provided.

### Build a block-shuffled disk layout

After building an in-memory Vamana index and the usual PQ files, create a
block-shuffled disk index with:

```bash
build/apps/utils/create_disk_layout <data_type> <base_file> <mem_index_file> <output_disk_index> block_shuffle <max_iterations> <gain_threshold> reorder_pq
```

Example:

```bash
build/apps/utils/create_disk_layout float data/sift/sift_learn.fbin data/sift/index_mem.index data/sift/index_disk.index block_shuffle 5 0.0001 reorder_pq
```

Use `reorder_pq` when the disk layout renumbers nodes. This rewrites
`<prefix>_pq_compressed.bin` so PQ distances are still looked up with the new
node ids used by the block-shuffled disk graph.

### Search baseline versus sector-aware mode

Baseline search keeps the original node-centric expansion:

```bash
build/apps/search_disk_index \
  --data_type float \
  --dist_fn l2 \
  --index_path_prefix data/sift/index \
  --result_path data/sift/res_baseline \
  --query_file data/sift/sift_query.fbin \
  --gt_file data/sift/sift_groundtruth.bin \
  -K 10 \
  -L 50 100 \
  -W 4 \
  --result_new_to_old_map data/sift/index_disk.index_block_shuffle_new_to_old.bin
```

Sector-aware search uses the same index and parameters, but adds:

```bash
  --use_sector_candidates
```

Full example:

```bash
build/apps/search_disk_index \
  --data_type float \
  --dist_fn l2 \
  --index_path_prefix data/sift/index \
  --result_path data/sift/res_sector_candidates \
  --query_file data/sift/sift_query.fbin \
  --gt_file data/sift/sift_groundtruth.bin \
  -K 10 \
  -L 50 100 \
  -W 4 \
  --result_new_to_old_map data/sift/index_disk.index_block_shuffle_new_to_old.bin \
  --use_sector_candidates
```

Use the same `-K`, `-L`, `-W`, thread count, cache size, and query set when
comparing the two modes. The useful comparison is baseline block-shuffled search
without `--use_sector_candidates` versus block-shuffled search with
`--use_sector_candidates`.

### WSL-native test recipe

Do not run the benchmark directly from `/mnt/c/...` or `/mnt/d/...` if you care
about disk I/O numbers. Copy the repo and data into the Linux filesystem first,
for example under `~`.

From WSL, copy the repo into `~/DiskANN` and work from there:

```bash
cd ~
rsync -a --exclude build --exclude build_clean /mnt/d/Papers/Diskann/DiskANN_cpp/ ~/DiskANN/
cd ~/DiskANN

mkdir -p build
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target search_disk_index create_disk_layout -j
```

Put your dataset files under the WSL-native workspace as well:

```bash
cd ~/DiskANN
mkdir -p data

# Example only. Replace these paths with your real local dataset paths.
cp /mnt/d/path/to/base.fbin data/base.fbin
cp /mnt/d/path/to/query.fbin data/query.fbin
cp /mnt/d/path/to/gt.bin data/gt.bin
```

Also copy the already-built memory index and PQ files into WSL. The examples
below assume they are renamed to the `PREFIX_DEFAULT` prefix:

```bash
cd ~/DiskANN
mkdir -p index

# Example only. Replace /mnt/d/path/to/original_index with your real prefix.
# These source files are:
#   original_index_mem.index
#   original_index_pq_pivots.bin
#   original_index_pq_compressed.bin
cp /mnt/d/path/to/original_index_mem.index index/default_mem.index
cp /mnt/d/path/to/original_index_pq_pivots.bin index/default_pq_pivots.bin
cp /mnt/d/path/to/original_index_pq_compressed.bin index/default_pq_compressed.bin
```

The commands below assume these variables. Adjust `DATA_TYPE`, `DIST_FN`,
`K`, `L_VALUES`, `W`, and `T` for your experiment:

```bash
cd ~/DiskANN

DATA_TYPE=float
DIST_FN=l2
BASE=~/DiskANN/data/base.fbin
QUERY=~/DiskANN/data/query.fbin
GT=~/DiskANN/data/gt.bin
PREFIX_DEFAULT=~/DiskANN/index/default
PREFIX_BLOCK=~/DiskANN/index/block
K=10
L_VALUES="20 30 40 50 60 100"
W=4
T=8

mkdir -p ~/DiskANN/index ~/DiskANN/results
```

Create a normal disk layout from an existing memory index:

```bash
build/apps/utils/create_disk_layout \
  ${DATA_TYPE} \
  ${BASE} \
  ${PREFIX_DEFAULT}_mem.index \
  ${PREFIX_DEFAULT}_disk.index \
  default
```

Create a block-shuffled disk layout from the same memory index. Use
`reorder_pq` so the in-memory PQ codes are renumbered consistently with the
block-shuffled graph ids:

```bash
build/apps/utils/create_disk_layout \
  ${DATA_TYPE} \
  ${BASE} \
  ${PREFIX_DEFAULT}_mem.index \
  ${PREFIX_BLOCK}_disk.index \
  block_shuffle \
  5 \
  0.0001 \
  reorder_pq
```

Run the normal layout baseline:

```bash
build/apps/search_disk_index \
  --data_type ${DATA_TYPE} \
  --dist_fn ${DIST_FN} \
  --index_path_prefix ${PREFIX_DEFAULT} \
  --result_path ~/DiskANN/results/default_baseline \
  --query_file ${QUERY} \
  --gt_file ${GT} \
  -K ${K} \
  -L ${L_VALUES} \
  -W ${W} \
  -T ${T} \
  --num_nodes_to_cache 0 \
  | tee ~/DiskANN/results/default_baseline.log
```

Run the block-shuffled layout with the original node-centric search. This
isolates the effect of renumbering the layout without using sector candidates:

```bash
build/apps/search_disk_index \
  --data_type ${DATA_TYPE} \
  --dist_fn ${DIST_FN} \
  --index_path_prefix ${PREFIX_BLOCK} \
  --result_path ~/DiskANN/results/block_baseline \
  --query_file ${QUERY} \
  --gt_file ${GT} \
  -K ${K} \
  -L ${L_VALUES} \
  -W ${W} \
  -T ${T} \
  --num_nodes_to_cache 0 \
  --result_new_to_old_map ${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin \
  | tee ~/DiskANN/results/block_baseline.log
```

Run the block-shuffled layout with sector-aware expansion enabled:

```bash
build/apps/search_disk_index \
  --data_type ${DATA_TYPE} \
  --dist_fn ${DIST_FN} \
  --index_path_prefix ${PREFIX_BLOCK} \
  --result_path ~/DiskANN/results/block_sector_candidates \
  --query_file ${QUERY} \
  --gt_file ${GT} \
  -K ${K} \
  -L ${L_VALUES} \
  -W ${W} \
  -T ${T} \
  --num_nodes_to_cache 0 \
  --result_new_to_old_map ${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin \
  --use_sector_candidates \
  | tee ~/DiskANN/results/block_sector_candidates.log
```

For the cleanest comparison, keep `--num_nodes_to_cache 0` at first. A large
node cache can hide disk-layout effects because many early expansions come from
memory instead of sector reads.
