#include <iostream>
#include <fstream>
#include <vector>
#include <map>
#include <array>
#include <set>
#include <algorithm>
#include <stdexcept>
#include <string>
#include "sim/Engine.h"
#include "ssd/FTL.h"
#include "ssd/TSU_OutofOrder.h"
#include "ssd/NVM_Transaction_Flash_RD.h"
using namespace SSD_Components;using namespace NVM::FlashMemory;
using T=sim_time_type;
struct Req {unsigned id,batch;uint64_t page;T offset,submit=0,demand=0,complete=0,dispatch=0,cmd=0,array=0,ready=0,data=0;bool submitted=false,requested=false,done=false;Physical_Page_Address addr;};
struct Batch {unsigned beam;T gap;std::vector<unsigned> ids;unsigned requested=0,done=0;bool closed=false;T start=0,finish=0;};
struct Query {unsigned id;T outside,start=0;std::vector<unsigned> batches;};
std::vector<Req> requests;std::vector<Batch> batches;std::vector<Query> queries;
std::ofstream events;
void lab_trace(const char* e,NVM_Transaction_Flash* tr){auto &r=requests.at(tr->LPA);T t=Simulator->Time();std::string s=e;
 if(s=="dispatch")r.dispatch=t;else if(s=="cmd_start")r.cmd=t;else if(s=="array_start")r.array=t;else if(s=="array_end")r.ready=t;else if(s=="data_start")r.data=t;
 if(r.id<1000)events<<t<<','<<e<<','<<r.id<<','<<r.batch<<','<<r.addr.ChannelID<<','<<r.addr.ChipID<<','<<r.addr.DieID<<'\n';
}
class NoGC:public GC_and_WL_Unit_Base{public:NoGC(unsigned blocks):GC_and_WL_Unit_Base("no_gc",nullptr,nullptr,nullptr,nullptr,GC_Block_Selection_Policy_Type::GREEDY,.1,true,.05,8,4,2,1,blocks,256,8,false,.1,1,false,false,1,1){} bool GC_is_in_urgent_mode(const Flash_Chip*) override{return false;}void Check_gc_required(unsigned int,const Physical_Page_Address&)override{}};
struct Ev{unsigned rid;bool demand;};
class Driver:public MQSimEngine::Sim_Object{public:static Driver*self;TSU_OutOfOrder*tsu;NVM_PHY_ONFI_NVDDR2*phy;bool oracle;unsigned qi=0,bi=0;std::ofstream qout,bout;T query_start=0;unsigned completed=0;
 Driver(TSU_OutOfOrder*t,NVM_PHY_ONFI_NVDDR2*p,bool o,std::string prefix):Sim_Object("driver"),tsu(t),phy(p),oracle(o),qout(prefix+"_queries.csv"),bout(prefix+"_batches.csv"){self=this;qout<<"query,window_ns,outside_ns,total_ns,reads,gap_ns\n";bout<<"query,beam,demand_ns,finish_ns,reads,gap_before_ns\n";}
 void Validate_simulation_config()override{}void Setup_triggers()override{Sim_Object::Setup_triggers();phy->ConnectToTransactionServicedSignal(done);}
 void Start_simulation()override{queries[0].start=0;launch(queries[0].batches[0],0,false);}
 void launch(unsigned b,T start,bool pre){auto &bb=batches[b];bb.start=start;for(auto id:bb.ids){requests[id].demand=start+requests[id].offset;Simulator->Register_sim_event(requests[id].demand,this,new Ev{id,true});if(pre)Simulator->Register_sim_event(Simulator->Time()+1+requests[id].offset,this,new Ev{id,false});}}
 static void done(NVM_Transaction_Flash*tr){auto&r=requests.at(tr->LPA);if(r.done)throw std::runtime_error("duplicate completion");r.done=true;r.complete=Simulator->Time();lab_trace("complete",tr);batches[r.batch].done++;self->completed++;self->close(r.batch);}
 void close(unsigned b){auto&bb=batches[b];if(bb.closed||bb.done!=bb.ids.size()||bb.requested!=bb.ids.size())return;bb.closed=true;bb.finish=Simulator->Time();auto&q=queries[qi];if(q.batches[bi]!=b)throw std::runtime_error("batch order");bout<<q.id<<','<<bb.beam<<','<<bb.start<<','<<bb.finish<<','<<bb.ids.size()<<','<<bb.gap<<'\n';
 if(++bi<q.batches.size()){unsigned next=q.batches[bi];launch(next,Simulator->Time()+std::max<T>(1,batches[next].gap),oracle);}
 else{T g=0;unsigned n=0;for(auto j:q.batches){g+=batches[j].gap;n+=batches[j].ids.size();}T win=Simulator->Time()-q.start;qout<<q.id<<','<<win<<','<<q.outside<<','<<win+q.outside<<','<<n<<','<<g<<'\n';if(++qi<queries.size()){bi=0;queries[qi].start=Simulator->Time()+1;launch(queries[qi].batches[0],queries[qi].start,false);}}
 }
 void Execute_simulator_event(MQSimEngine::Sim_Event*ev)override{auto e=*(Ev*)ev->Parameters;delete (Ev*)ev->Parameters;auto&r=requests[e.rid];if(e.demand){r.requested=true;batches[r.batch].requested++;}if(!r.submitted){r.submitted=true;r.submit=Simulator->Time();auto tr=new NVM_Transaction_Flash_RD(Transaction_Source_Type::USERIO,0,4096,r.id,r.id,r.addr,nullptr,0,nullptr,255,0);lab_trace("submit",tr);tsu->Prepare_for_transaction_submit();tsu->Submit_transaction(tr);tsu->Schedule();}close(r.batch);}
};Driver*Driver::self=nullptr;
uint64_t mix(uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
int main(int argc,char**argv){if(argc<6)return 2;std::ifstream in(argv[1]);bool oracle=std::string(argv[2])=="oracle";std::string prefix=argv[3];bool hashed=std::string(argv[4])=="hash";T read_ns=std::stoull(argv[5]);unsigned nq;in>>nq;
 for(unsigned q=0;q<nq;q++){Query query;unsigned nb;in>>query.id>>query.outside>>nb;for(unsigned j=0;j<nb;j++){Batch b;unsigned nr;in>>b.beam>>b.gap>>nr;unsigned bid=batches.size();query.batches.push_back(bid);for(unsigned k=0;k<nr;k++){Req r;r.id=requests.size();r.batch=bid;in>>r.page>>r.offset;b.ids.push_back(r.id);requests.push_back(r);}batches.push_back(b);}queries.push_back(query);}if(!in)throw std::runtime_error("input parse");
 std::array<std::map<uint64_t,unsigned>,64> mapping;unsigned maxpages=0;for(auto&r:requests){uint64_t p=hashed?mix(r.page):r.page;unsigned ch=p%8,chip=(p/8)%4,die=(p/32)%2,key=ch+8*chip+32*die;auto&m=mapping[key];auto it=m.find(r.page);unsigned index;if(it==m.end()){index=m.size();m[r.page]=index;}else index=it->second;maxpages=std::max(maxpages,index+1);r.addr=Physical_Page_Address(ch,chip,die,0,index/256,index%256);}
 unsigned blocks=(maxpages+255)/256;Simulator->Reset();T rd[3]={read_ns,read_ns,read_ns},wr[3]={200000,200000,200000};auto channels=new ONFI_Channel_NVDDR2*[8];for(unsigned ch=0;ch<8;ch++){auto chips=new Flash_Chip*[4];for(unsigned c=0;c<4;c++){chips[c]=new Flash_Chip("chip"+std::to_string(ch)+"_"+std::to_string(c),ch,c,Flash_Technology_Type::SLC,2,1,blocks,256,rd,wr,1000000,0,0,0,0,0);Simulator->AddObject(chips[c]);}channels[ch]=new ONFI_Channel_NVDDR2(ch,4,chips,1);}
 auto phy=new NVM_PHY_ONFI_NVDDR2("phy",channels,8,4,2,1);auto ftl=new FTL("ftl",nullptr,8,4,2,1,blocks,256,8,read_ns,200000,.1,100,1);ftl->GC_and_WL_Unit=new NoGC(blocks);auto tsu=new TSU_OutOfOrder("tsu",ftl,phy,8,4,2,1,0,0,0,false,false);auto driver=new Driver(tsu,phy,oracle,prefix);
 events.open(prefix+"_events.csv");events<<"time_ns,event,id,batch,channel,chip,die\n";Simulator->AddObject(phy);Simulator->AddObject(tsu);Simulator->AddObject(driver);Simulator->Start_simulation();if(driver->completed!=requests.size()||driver->qi!=queries.size())throw std::runtime_error("incomplete");driver->qout.flush();driver->bout.flush();
 std::ofstream ro(prefix+"_requests.csv");ro<<"id,batch,page,channel,chip,die,block,physical_page,submit_ns,demand_ns,dispatch_ns,cmd_ns,array_ns,ready_ns,data_ns,complete_ns\n";for(auto&r:requests){if(!(r.submit<=r.dispatch&&r.dispatch<=r.cmd&&r.cmd<=r.array&&r.array<=r.ready&&r.ready<=r.data&&r.data<=r.complete))throw std::runtime_error("chronology");ro<<r.id<<','<<r.batch<<','<<r.page<<','<<r.addr.ChannelID<<','<<r.addr.ChipID<<','<<r.addr.DieID<<','<<r.addr.BlockID<<','<<r.addr.PageID<<','<<r.submit<<','<<r.demand<<','<<r.dispatch<<','<<r.cmd<<','<<r.array<<','<<r.ready<<','<<r.data<<','<<r.complete<<'\n';}
}
