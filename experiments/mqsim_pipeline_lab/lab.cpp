#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include "sim/Engine.h"
#include "ssd/FTL.h"
#include "ssd/TSU_OutofOrder.h"
#include "ssd/NVM_Transaction_Flash_RD.h"
using namespace SSD_Components;
using namespace NVM::FlashMemory;
void lab_trace(const char* event, NVM_Transaction_Flash* tr) {
 auto a=tr->Address;
 std::cout<<Simulator->Time()<<","<<event<<","<<tr->LPA<<","<<a.ChannelID<<","<<a.ChipID<<","<<a.DieID<<","<<a.PlaneID<<","<<a.PageID<<"\n";
}
// Only supplies the non-urgent-GC predicate to the unchanged scheduler.
// Not registered with Engine: no FTL translation, cache, GC callbacks or host path.
class NoGC : public GC_and_WL_Unit_Base {
public:
 NoGC():GC_and_WL_Unit_Base("no_gc",nullptr,nullptr,nullptr,nullptr,
 GC_Block_Selection_Policy_Type::GREEDY,0.1,true,0.05,2,2,2,1,4,64,8,false,0.1,1,false,false,1,1){}
 bool GC_is_in_urgent_mode(const Flash_Chip*) override {return false;}
 void Check_gc_required(unsigned int,const Physical_Page_Address&) override {}
};
class Driver : public MQSimEngine::Sim_Object {
public:
 static Driver* self;
 TSU_OutOfOrder* tsu; NVM_PHY_ONFI_NVDDR2* phy;
 std::string mode; std::vector<NVM_Transaction_Flash_RD*> req;
 unsigned next=0,completed=0,inflight=0; unsigned window=4; sim_time_type gap=0;
 Driver(std::string m,TSU_OutOfOrder* t,NVM_PHY_ONFI_NVDDR2* p,sim_time_type g):Sim_Object("driver"),tsu(t),phy(p),mode(m),gap(g){self=this;}
 void Setup_triggers() override { Sim_Object::Setup_triggers(); phy->ConnectToTransactionServicedSignal(done); }
 void Validate_simulation_config() override {}
 void Start_simulation() override {Simulator->Register_sim_event(0,this);}
 void add(unsigned ch,unsigned chip,unsigned die,unsigned page){
  unsigned id=req.size(); Physical_Page_Address a(ch,chip,die,0,0,page);
  req.push_back(new NVM_Transaction_Flash_RD(Transaction_Source_Type::USERIO,0,4096,id,id,a,nullptr,0,nullptr,255,0));
 }
 static void done(NVM_Transaction_Flash* tr){
  lab_trace("complete",tr); self->completed++;self->inflight--;
  if(self->next>=self->req.size())return;
  if(self->mode=="stream") Simulator->Register_sim_event(Simulator->Time()+1,self,nullptr,1);
  else if(self->inflight==0) Simulator->Register_sim_event(Simulator->Time()+self->gap+1,self);
 }
 void Execute_simulator_event(MQSimEngine::Sim_Event* ev) override {
  unsigned n=ev->Type==1?1:window;
  if(mode=="phy_die_interleave") {
   while(next<req.size()) {auto tr=req[next++];lab_trace("submit",tr);inflight++;
    std::list<NVM_Transaction_Flash*> one{tr};phy->Send_command_to_chip(one);}
   return;
  }
  tsu->Prepare_for_transaction_submit();
  while(n-- && next<req.size() && inflight<window){auto tr=req[next++];lab_trace("submit",tr);inflight++;tsu->Submit_transaction(tr);}
  tsu->Schedule();
 }
};
Driver* Driver::self=nullptr;
int main(int argc,char**argv){
 if(argc<2) return 2;
 Simulator->Reset();
 std::string mode=argv[1];sim_time_type gap=argc>2?std::stoull(argv[2]):0;
 sim_time_type r[3]={50000,50000,50000},w[3]={200000,200000,200000};
 auto channels=new ONFI_Channel_NVDDR2*[2];
 for(unsigned ch=0;ch<2;ch++){
  auto chips=new Flash_Chip*[2];
  for(unsigned c=0;c<2;c++){
   chips[c]=new Flash_Chip("chip"+std::to_string(ch)+std::to_string(c),ch,c,Flash_Technology_Type::SLC,2,1,4,64,r,w,1000000,0,0,0,0,0);
   Simulator->AddObject(chips[c]);
  }
  channels[ch]=new ONFI_Channel_NVDDR2(ch,2,chips,1);
 }
 auto phy=new NVM_PHY_ONFI_NVDDR2("phy",channels,2,2,2,1);
 auto ftl=new FTL("ftl",nullptr,2,2,2,1,4,64,8,50000,200000,0.1,100,1);
 ftl->GC_and_WL_Unit=new NoGC();
 auto tsu=new TSU_OutOfOrder("tsu",ftl,phy,2,2,2,1,0,0,0,false,false);
 auto driver=new Driver(mode,tsu,phy,gap);
 if(mode=="channels"){driver->add(0,0,0,0);driver->add(1,0,0,1);}
 else if(mode=="chips"){driver->add(0,0,0,0);driver->add(0,1,0,1);}
 else if(mode=="dies"||mode=="phy_die_interleave"){driver->add(0,0,0,0);driver->add(0,0,1,1);}
 else if(mode=="pages"){driver->add(0,0,0,0);driver->add(0,0,0,1);}
 else if(mode=="batch"||mode=="stream"){
  // Identical ordered physical-address sequence, four independent chips per round.
  for(unsigned i=0;i<16;i++)driver->add(i%2,(i/2)%2,0,i/4);
 }else return 2;
 std::cout<<"time_ns,event,id,channel,chip,die,plane,page\n";
 Simulator->AddObject(phy);Simulator->AddObject(tsu);Simulator->AddObject(driver);
 Simulator->Start_simulation();
 if(driver->completed!=driver->req.size())throw std::runtime_error("Incomplete requests");
 // Process exits after one experiment; objects intentionally live until exit.
 return 0;
}
