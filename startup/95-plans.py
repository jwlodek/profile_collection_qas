import bluesky as bs
import bluesky.plans as bp
import time as ttime
from subprocess import call
import os
import signal


def general_scan_plan(detectors, motor, rel_start, rel_stop, num):

    
    plan = bp.relative_scan(detectors, motor, rel_start, rel_stop, num)
    
    if hasattr(detectors[0], 'kickoff'):
        plan = bp.fly_during_wrapper(plan, detectors)

    yield from plan


def prep_traj_plan(delay = 0.1):
    yield from bp.abs_set(mono1.prepare_trajectory, '1', wait=True)

    # Poll the trajectory ready pv
    while True:
        ret = (yield from bp.read(mono1.trajectory_ready))
        if ret is None:
            break
        is_running = ret['mono1_trajectory_ready']['value']

        if is_running:
            break
        else:
            yield from bp.sleep(.1)

    while True:
        ret = (yield from bp.read(mono1.trajectory_ready))
        if ret is None:
            break
        is_running = ret['mono1_trajectory_ready']['value']

        if is_running:
            yield from bp.sleep(.05)
        else:
            break

    yield from bp.sleep(delay)

    curr_energy = (yield from bp.read(mono1.energy))

    if curr_energy is None:
        return
        raise Exception('Could not read current energy')

    curr_energy = curr_energy['mono1_energy']['value']
    print('Curr Energy: {}'.format(curr_energy))
    if curr_energy >= 12000:
        print('>12000')
        yield from bp.mv(mono1.energy, curr_energy + 100)
        yield from bp.sleep(1)
        print('1')
        yield from bp.mv(mono1.energy, curr_energy)


def execute_trajectory(name, **metadata):
    flyers = [pb1.enc1]
    def inner():
        curr_traj = getattr(mono1, 'traj{:.0f}'.format(mono1.lut_number_rbv.value))
        md = {'plan_args': {},
              'plan_name': 'execute_trajectory',
              'experiment': 'transmission',
              'name': name,
              'angle_offset': str(mono1.angle_offset.value),
              'trajectory_name': mono1.trajectory_name.value,
              'element': curr_traj.elem.value,
              'edge': curr_traj.edge.value}
        for flyer in flyers:
            if hasattr(flyer, 'offset'):
                md['{} offset'.format(flyer.name)] = flyer.offset.value
        md.update(**metadata)
        yield from bp.open_run(md=md)

        # TODO Replace this with actual status object logic.
        yield from bp.clear_checkpoint()
        #yield from shutter.open_plan()
        #yield from xia1.start_trigger()
        # this must be a float
        yield from bp.abs_set(mono1.enable_loop, 0, wait=True)
        # this must be a string
        yield from bp.abs_set(mono1.start_trajectory, '1', wait=True)

        # this should be replaced by a status object
        def poll_the_traj_plan():
            while True:
                ret = (yield from bp.read(mono1.trajectory_running))
                if ret is None:
                    break
                is_running = ret['mono1_trajectory_running']['value']

                if is_running:
                    break
                else:
                    yield from bp.sleep(.1)

            while True:
                ret = (yield from bp.read(mono1.trajectory_running))
                if ret is None:
                    break
                is_running = ret['mono1_trajectory_running']['value']

                if is_running:
                    yield from bp.sleep(.05)
                else:
                    break


        yield from bp.finalize_wrapper(poll_the_traj_plan(), 
                                       bp.abs_set(mono1.stop_trajectory, '1', wait=True)
                                      )

        yield from bp.close_run()

    def final_plan():
        yield from bp.abs_set(mono1.trajectory_running, 0, wait=True)
        #yield from xia1.stop_trigger()
        for flyer in flyers:
            yield from bp.unstage(flyer)
        yield from bp.unstage(mono1)

    for flyer in flyers:
        yield from bp.stage(flyer)

    yield from bp.stage(mono1)

    return (yield from bp.fly_during_wrapper(bp.finalize_wrapper(inner(), final_plan()),
                                              flyers))
