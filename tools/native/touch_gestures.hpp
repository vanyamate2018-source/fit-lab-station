#pragma once
#include <cmath>
#include <functional>
#include <vector>

namespace fitlab {
struct Point { int id; double x, y; };
enum Kind { Move, Down, Up, Scroll };
struct Action { Kind kind; double x, y, delta=0; };
class Gestures {
    enum Mode { Idle, Pending, Dragging, Scrolling, Suppressed } mode=Idle;
    Point start{}, last{};
    double began=0, centerY=0;
    std::function<void(Action)> emit;
public:
    explicit Gestures(std::function<void(Action)> callback):emit(callback){}
    void cancel() {
        if (mode==Dragging) emit({Up,last.x,last.y});
        mode=Idle;
    }
    void hold(double now) {
        if (mode==Pending && now-began>.4) {
            emit({Move,start.x,start.y}); emit({Down,start.x,start.y}); mode=Dragging;
        }
    }
    void update(const std::vector<Point>& points, double now) {
        if (points.empty()) {
            if (mode==Pending) { emit({Move,last.x,last.y}); emit({Down,last.x,last.y}); emit({Up,last.x,last.y}); }
            else if (mode==Dragging) emit({Up,last.x,last.y});
            mode=Idle; return;
        }
        if (mode==Idle) {
            start=last=points.front(); began=now;
            mode=points.size()==1 ? Pending : Scrolling;
            centerY=0; for(auto p:points) centerY+=p.y; centerY/=points.size();
            if(mode==Scrolling) emit({Move,start.x,start.y});
            return;
        }
        if (mode==Suppressed) return;
        if (mode==Scrolling || (mode==Pending && points.size()>1)) {
            if(points.size()!=2) { mode=Suppressed; return; }
            double center=(points[0].y+points[1].y)/2;
            if (mode==Scrolling) emit({Scroll,points[0].x,points[0].y,center-centerY});
            mode=Scrolling; centerY=center; return;
        }
        const Point* current=nullptr;
        for(const auto& p:points) if(p.id==start.id) current=&p;
        if(!current) { cancel(); mode=Suppressed; return; }
        last=*current;
        if(mode==Pending && std::hypot(last.x-start.x,last.y-start.y)>7) {
            emit({Move,start.x,start.y}); emit({Down,start.x,start.y}); mode=Dragging;
        }
        if(mode==Dragging) emit({Move,last.x,last.y});
    }
};
}
