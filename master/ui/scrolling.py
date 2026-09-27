"""Touch scrolling with bounded inertia and no elastic overscroll."""
import sys
from PySide6.QtWidgets import QScroller, QScrollerProperties


def configure_touch_scrolling(scroll_area, pointer_drag=True):
    viewport = scroll_area.viewport()
    if viewport.property('fitlabScrollReady'):
        return
    viewport.setProperty('fitlabScrollReady', True)
    # X11 touch panels may expose pointer compatibility events. Handle their
    # drags too, rather than requiring native Qt TouchBegin on every driver.
    gesture = QScroller.ScrollerGestureType.LeftMouseButtonGesture if pointer_drag or sys.platform == 'linux' else QScroller.ScrollerGestureType.TouchGesture
    QScroller.grabGesture(viewport, gesture)
    scroller = QScroller.scroller(viewport)
    properties = scroller.scrollerProperties()
    metric = QScrollerProperties.ScrollMetric
    properties.setScrollMetric(metric.DragStartDistance, .003)
    properties.setScrollMetric(metric.MousePressEventDelay, .06)
    properties.setScrollMetric(metric.AxisLockThreshold, .75)
    properties.setScrollMetric(metric.DecelerationFactor, .2)
    properties.setScrollMetric(metric.MaximumVelocity, .6)
    properties.setScrollMetric(metric.MaximumClickThroughVelocity, 0.0)
    properties.setScrollMetric(metric.HorizontalOvershootPolicy,
                               QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
    properties.setScrollMetric(metric.VerticalOvershootPolicy,
                               QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
    scroller.setScrollerProperties(properties)
