from ophyd.areadetector import (AreaDetector, PixiradDetectorCam, ImagePlugin,
                                TIFFPlugin, StatsPlugin, HDF5Plugin,
                                ProcessPlugin, ROIPlugin, TransformPlugin,
                                OverlayPlugin)
from ophyd.areadetector.plugins import PluginBase
from ophyd.areadetector.cam import AreaDetectorCam
from ophyd.device import BlueskyInterface
from ophyd.areadetector.trigger_mixins import SingleTrigger
from ophyd.areadetector.filestore_mixins import (FileStoreIterativeWrite,
                                                 FileStoreHDF5IterativeWrite,
                                                 FileStoreTIFFSquashing,
                                                 FileStoreTIFF)
from ophyd import Signal
from ophyd import Component as Cpt

from hxntools.handlers import register
register(db)

from pathlib import PurePath
from hxntools.detectors.xspress3 import (XspressTrigger, Xspress3Detector,
                                         Xspress3Channel, Xspress3FileStore, logger)
from databroker.assets.handlers import Xspress3HDF5Handler, HandlerBase


class QasXspress3Detector(XspressTrigger, Xspress3Detector):
    roi_data = Cpt(PluginBase, 'ROIDATA:')
    channel1 = Cpt(Xspress3Channel, 'C1_', channel_num=1, read_attrs=['rois'])
    channel2 = Cpt(Xspress3Channel, 'C2_', channel_num=2, read_attrs=['rois'])
    channel3 = Cpt(Xspress3Channel, 'C3_', channel_num=3, read_attrs=['rois'])
    channel4 = Cpt(Xspress3Channel, 'C4_', channel_num=4, read_attrs=['rois'])
    # create_dir = Cpt(EpicsSignal, 'HDF5:FileCreateDir')

    hdf5 = Cpt(Xspress3FileStore, 'HDF5:',
               read_path_template='/nsls2/xf07bm/data/x3m/%Y/%m/%d/',
               root='/nsls2/xf07bm/data/',
               write_path_template='/nsls2/xf07bm/data/x3m/%Y/%m/%d/',
               )

    def __init__(self, prefix, *, configuration_attrs=None, read_attrs=None,
                 **kwargs):
        if configuration_attrs is None:
            configuration_attrs = ['external_trig', 'total_points',
                                   'spectra_per_point', 'settings',
                                   'rewindable']
        if read_attrs is None:
            read_attrs = ['channel1', 'channel2', 'channel3', 'channel4', 'hdf5']
        super().__init__(prefix, configuration_attrs=configuration_attrs,
                         read_attrs=read_attrs, **kwargs)
        # self.create_dir.put(-3)

    def stop(self):
        ret = super().stop()
        self.hdf5.stop()
        return ret

    def stage(self):
        # self.external_trig.put(True)
        # self.settings.trigger_mode.put(3)  # 'TTL Veto Only'
        if self.spectra_per_point.get() != 1:
            raise NotImplementedError(
                "multi spectra per point not supported yet")
        ret = super().stage()
        # self._resource_uid = self._resource
        return ret

    # def unstage(self):
    #     self.settings.trigger_mode.put(0)  # 'Software'
    #     super().unstage()

    # Currently only using three channels. Uncomment these to enable more
    # channels:
    # channel5 = C(Xspress3Channel, 'C5_', channel_num=5)
    # channel6 = C(Xspress3Channel, 'C6_', channel_num=6)
    # channel7 = C(Xspress3Channel, 'C7_', channel_num=7)
    # channel8 = C(Xspress3Channel, 'C8_', channel_num=8)


xs = QasXspress3Detector('XF:07BMB-ES{Xsp:1}:', name='xs')
for n in [1, 2, 3, 4]:
    getattr(xs, f'channel{n}').rois.read_attrs = ['roi{:02}'.format(j) for j in [1, 2, 3, 4]]
xs.hdf5.num_extra_dims.put(0)
xs.channel2.vis_enabled.put(1)
xs.channel3.vis_enabled.put(1)
xs.settings.num_channels.put(4)


class XSFlyer:
    def __init__(self, det, pbs, pb_trigger, motor):
        # self.name = f'{det.name}-{"-".join([pb.name for pb in pbs])}-flyer'
        self.parent = None
        self.det = det  # xspress3 device
        self.pbs = pbs  # a list of passed pizza-boxes
        self.motor = motor
        self.pb_trigger = pb_trigger
        self._motor_status = None

    def kickoff(self, *args, **kwargs):
        self.det.stage()
        self.det.total_points.put()

    def calc_num_points(self):
        tr = trajectory_manager(self.motor)
        info = tr.read_info(silent=True)
        lut = str(int(self.motor.lut_number_rbv.get()))
        traj_duration = int(info[lut]['size']) / 16000
        if self.pb_trigger.unit_sel.get()==0:
             multip = 1e-6
        else:
             multip = 1e-3
        acq_num_points = traj_duration/ (self.pb_trigger.period_sp.get() * multip) * 1.3
        print(f'acq_num_points: {acq_num_points}\ntraj_dur: {traj_duration}')
        self.num_points = int(round(acq_num_points, ndigits=0))

xsflyer = XSFlyer(xs, [], pb2.do1, mono1)

# This is necessary for when the ioc restarts
# we have to trigger one image for the hdf5 plugin to work correclty
# else, we get file writing errors
# xs.hdf5.warmup()

# Hints:
for n in [1, 2]:
    getattr(xs, f'channel{n}').rois.roi01.value.kind = 'hinted'

# import skbeam.core.constants.xrf as xrfC
#
# interestinglist = ['Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U']
#
# elements = dict()
# element_edges = ['ka1','ka2','kb1','la1','la2','lb1','lb2','lg1','ma1']
# element_transitions = ['k', 'l1', 'l2', 'l3', 'm1', 'm2', 'm3', 'm4', 'm5']
# for i in interestinglist:
#     elements[i] = xrfC.XrfElement(i)
#
# def setroi(roinum, element, edge):
#     '''
#     Set energy ROIs for Vortex SDD.  Selects elemental edge given current energy if not provided.
#     roinum      [1,2,3]     ROI number
#     element     <symbol>    element symbol for target energy
#     edge                    optional:  ['ka1','ka2','kb1','la1','la2','lb1','lb2','lg1','ma1']
#     '''
#
#     cur_element = xrfC.XrfElement(element)
#
#     e_ch = int(cur_element.emission_line[edge] * 1000)
#
#     for (n, d) in xs.channels.items():
#         d.set_roi(roinum, e_ch-200, e_ch+200, name=element + '_' + edge)
#         getattr(d.rois, f'roi{roinum:02d}').kind = 'normal'
#     print("ROI{} set for {}-{} edge.".format(roinum, element, edge))
#
#
# def clearroi(roinum=None):
#     if roinum is None:
#         roinum = [1, 2, 3]
#     try:
#         roinum = list(roinum)
#     except TypeError:
#         roinum = [roinum]
#
#     # xs.channel1.rois.roi01.clear
#     for (n, d) in xs.channels.items():
#         for roi in roinum:
#              cpt = getattr(d.rois, f'roi{roi:02d}')
#              cpt.clear()
#              cpt.kind = 'omitted'
#
xs.settings.configuration_attrs = ['acquire_period',
			           'acquire_time',
			           'gain',
			           'image_mode',
			           'manufacturer',
			           'model',
			           'num_exposures',
			           'num_images',
			           'temperature',
			           'temperature_actual',
			           'trigger_mode',
			           'config_path',
			           'config_save_path',
			           'invert_f0',
			           'invert_veto',
			           'xsp_name',
			           'num_channels',
			           'num_frames_config',
			           'run_flags',
                                   'trigger_signal']

for n, d in xs.channels.items():
    roi_names = ['roi{:02}'.format(j) for j in [1, 2, 3, 4]]
    d.rois.read_attrs = roi_names
    d.rois.configuration_attrs = roi_names
    for roi_n in roi_names:
        getattr(d.rois, roi_n).value_sum.kind = 'omitted'


