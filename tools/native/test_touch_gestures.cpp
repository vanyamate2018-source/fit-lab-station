#include "touch_gestures.hpp"
#include <cassert>
#include <iostream>
using namespace fitlab;
int main() {
 std::vector<Action> events;
 Gestures g([&](Action a){events.push_back(a);});
 g.update({{1,20,30}},0); assert(events.empty());
 g.update({},.1); assert(events.size()==3 && events[1].kind==Down && events[2].kind==Up);
 events.clear();g.update({{1,20,30}},1);g.update({{1,50,30}},1.1);
 assert(events[1].kind==Down);g.update({},1.2);assert(events.back().kind==Up);
 events.clear();g.update({{1,20,30}},2);g.update({{1,20,30},{2,50,30}},2.05);
 g.update({{1,20,60},{2,50,60}},2.1);g.update({},2.2);
 assert(events.size()==1 && events[0].kind==Scroll && events[0].delta==30);
 events.clear();g.update({{1,20,30}},3);g.cancel();g.update({},3.1);assert(events.empty());
 g.update({{1,20,30}},4);g.hold(4.5);g.cancel();assert(events.back().kind==Up);
 events.clear();g.update({{1,20,30},{2,50,30}},5);g.update({{2,50,60}},5.1);g.update({},5.2);
 for(auto a:events) assert(a.kind!=Down);
 std::cout<<"PASS: tap, drag, two-finger scroll, hold, cancellation, no extra tap after scroll\n";
}
