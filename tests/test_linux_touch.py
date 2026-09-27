from shared.linux_touch import discover


def add(root, name, props, axes):
    d=root/name/'device'; (d/'capabilities').mkdir(parents=True); (d/'id').mkdir()
    for file,value in {'name':'QDtech MPI7009','properties':props,'capabilities/abs':axes,'id/vendor':'0712','id/product':'0009'}.items():
        (d/file).write_text(value)


def test_native_digitizer_hotplug_and_touchpad_exclusion(tmp_path):
    add(tmp_path,'event8','2','260800000000003')
    add(tmp_path,'event9','1','260800000000003')
    touch=discover(tmp_path)
    assert len(touch)==1 and touch[0]['multitouch'] and touch[0]['vendor']=='0712'
    (tmp_path/'event8/device/properties').unlink()
    assert discover(tmp_path)==[]
