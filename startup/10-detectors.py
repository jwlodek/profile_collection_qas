print(__file__)
import uuid
from collections import namedtuple, deque
import os
import shutil
import time as ttime
from ophyd import (ProsilicaDetector, SingleTrigger, Component as Cpt, Device,
                   EpicsSignal, EpicsSignalRO, ImagePlugin, StatsPlugin, ROIPlugin,
                   DeviceStatus)
from ophyd.status import Status
from ophyd import DeviceStatus
from bluesky.examples import NullStatus

from databroker.assets.handlers_base import HandlerBase
from ophyd import (Component as C, FormattedComponent as FC)

from datetime import datetime

print("init bpm")
class BPM(ProsilicaDetector, SingleTrigger):
    image = Cpt(ImagePlugin, 'image1:')
    stats1 = Cpt(StatsPlugin, 'Stats1:')
    stats2 = Cpt(StatsPlugin, 'Stats2:')
    roi1 = Cpt(ROIPlugin, 'ROI1:')
    roi2 = Cpt(ROIPlugin, 'ROI2:')
    counts = Cpt(EpicsSignal, 'Pos:Counts')
    # Dan Allan guessed about the nature of these signals. Fix them if you need them.
    ins = Cpt(EpicsSignal, 'Cmd:In-Cmd')
    ret = Cpt(EpicsSignal, 'Cmd:Out-Cmd')
    switch_insert = Cpt(EpicsSignalRO, 'Sw:InLim-Sts')
    switch_retract = Cpt(EpicsSignalRO, 'Sw:OutLim-Sts')
    polarity = 'pos'

    def insert(self):
        self.ins.put(1)

    def retract(self):
        self.ret.put(1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_sigs.clear()  # default stage sigs do not apply

print("init CAMERA")
class CAMERA(ProsilicaDetector, SingleTrigger):
    image = Cpt(ImagePlugin, 'image1:')
    stats1 = Cpt(StatsPlugin, 'Stats1:')
    stats2 = Cpt(StatsPlugin, 'Stats2:')
    roi1 = Cpt(ROIPlugin, 'ROI1:')
    roi2 = Cpt(ROIPlugin, 'ROI2:')
    polarity = 'pos'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_sigs.clear()  # default stage sigs do not apply


colmirror_diag = CAMERA('XF:07BM-BI{Mir:Col}', name='colmirror_diag')
screen_diag = CAMERA('XF:07BM-BI{FS:1}', name='screen_diag') # HOW TO CALL CAMERA UNDER FT DIAGNOSTICS > Diagnostic Screen
mono_diag = CAMERA('XF:07BMA-BI{Mono:1}', name='mono_diag')
dcr_diag = CAMERA('XF:07BMB-BI{Diag:1}', name='dcr_diag')

# Prosilica detector in hutch 7-BM-B
hutchb_diag = CAMERA('XF:07BMB-BI{Diag:1}', name='hutchb_diag')


for camera in [colmirror_diag, screen_diag, mono_diag, dcr_diag, hutchb_diag]:
    #camera.read_attrs = ['stats1', 'stats2']
    #camera.image.read_attrs = ['array_data']
    camera.image.array_data.kind = 'normal'
    camera.stats1.total.kind = 'normal'
    camera.stats1.centroid.kind = 'normal'
    camera.stats2.total.kind = 'normal'
    camera.stats2.centroid.kind = 'normal'
    camera.stats1.total.kind = 'hinted'
    camera.stats2.total.kind = 'hinted'


# TODO: Move this class to ophyd. Same class is also used at ISS.
class Encoder(Device):
    """This class defines components but does not implement actual reading.

    See EncoderFS and EncoderParser"""
    pos_I = Cpt(EpicsSignal, '}Cnt:Pos-I')
    sec_array = Cpt(EpicsSignal, '}T:sec_Bin_')
    nsec_array = Cpt(EpicsSignal, '}T:nsec_Bin_')
    pos_array = Cpt(EpicsSignal, '}Cnt:Pos_Bin_')
    index_array = Cpt(EpicsSignal, '}Cnt:Index_Bin_')
    data_array = Cpt(EpicsSignal, '}Data_Bin_')
    # The '$' in the PV allows us to write 40 chars instead of 20.
    filepath = Cpt(EpicsSignal, '}ID:File.VAL', string=True)
    dev_name = Cpt(EpicsSignal, '}DevName')

    filter_dy = Cpt(EpicsSignal, '}Fltr:dY-SP')
    filter_dt = Cpt(EpicsSignal, '}Fltr:dT-SP')
    reset_counts = Cpt(EpicsSignal, '}Rst-Cmd')

    ignore_rb = Cpt(EpicsSignal, '}Ignore-RB')
    ignore_sel = Cpt(EpicsSignal, '}Ignore-Sel')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ready_to_collect = False
        if self.connected:
            self.ignore_sel.put(1)

def make_filename(filename):
    '''
        Makes a rootpath, filepath pair
    '''
    # RAW_FILEPATH is a global defined in 00-startup.py
    write_path_template = os.path.join(RAW_FILEPATH, '%Y/%m/%d')
    # path without the root
    filepath = os.path.join(datetime.now().strftime(write_path_template), filename)
    return filepath


# TODO: Move this class to ophyd.
class EncoderFS(Encoder):
    "Encoder Device, when read, returns references to data in filestore."
    chunk_size = 2**20
    write_path_template = '/data/nsls2/qas-new/legacy/raw/pizza_box_data/%Y/%m/%d/'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._asset_docs_cache = deque()
        self._resource_uid = None
        self._datum_counter = None

    def collect_asset_docs(self):
        items = list(self._asset_docs_cache)
        self._asset_docs_cache.clear()
        for item in items:
            yield item

    def stage(self):
        "Set the filename and record it in a 'resource' document in the filestore database."

        if self.connected:
            print('Staging of {} starting'.format(self.name))
            #write_path_template = '/data/nsls2/qas-new/legacy/raw/pizza_box_data/%Y/%m/%d/'

            filename = 'en_' + str(uuid.uuid4())[:6]
            write_path_template = os.path.join('pizza_box_data/%Y/%m/%d', filename)
            # path without the root
            resource_path = datetime.now().strftime(write_path_template)
            #ROOT_PATH = '/home/xf07bm/TestData/'
            filepath = os.path.join(ROOT_PATH, RAW_FILEPATH, resource_path)
                
            # without the root, but with data path + date folders
            self._full_path = filepath
            # FIXME: Quick TEMPORARY fix for beamline disaster
            # we are writing the file to a temp directory in the ioc and
            # then moving it to the GPFS system.
            #
            #ioc_file_root = '/home/softioc/tmp/'
            #self._ioc_full_path = os.path.join(ioc_file_root, filename)
            #self._filename = filename

            self.filepath.put(self._full_path)   # commented out during disaster
            #self.filepath.put(self._ioc_full_path)

            self._resource_uid = str(uuid.uuid4())
            resource = {'spec': 'PIZZABOX_ENC_FILE_TXT',
                        'root': os.path.join(ROOT_PATH, RAW_FILEPATH),
                        'resource_path': resource_path,
                        'resource_kwargs': {'chunk_size': self.chunk_size},
                        'path_semantics': {'posix': 'posix', 'nt': 'windows'}[os.name],
                        'uid': self._resource_uid}
            self._asset_docs_cache.append(('resource', resource))
            self._datum_counter = itertools.count()
            
            super().stage()
            print('Staging of {} complete'.format(self.name))

    def unstage(self):
        if self.connected:
            self.ignore_sel.set(1).wait()
            self._datum_counter = None
            return super().unstage()

    def kickoff(self):
        print('kickoff', self.name)
        self._ready_to_collect = True
        "Start writing data into the file."

        self.ignore_sel.set(0).wait()

        # Return a 'status object' that immediately reports we are 'done' ---
        # ready to collect at any time.
        return NullStatus()

    def complete(self):
        print('storing', self.name, 'in', self._full_path)
        if not self._ready_to_collect:
            raise RuntimeError("must called kickoff() method before calling complete()")
        # Stop adding new data to the file.
        self.ignore_sel.set(1).wait()
        #while not os.path.isfile(self._full_path):
        #    ttime.sleep(.1)

        # FIXME: beam line disaster fix.
        # Let's move the file to the correct place
        #workstation_file_root = '/mnt/xf08ida-ioc1/'
        #workstation_full_path = os.path.join(workstation_file_root, self._filename)
        #print('Moving file from {} to {}'.format(workstation_full_path, self._full_path))
        #cp_stat = shutil.copy(workstation_full_path, self._full_path)


        # HACK: Make datum documents here so that they are available for collect_asset_docs
        # before collect() is called. May need changes to RE to do this properly. - Dan A.

        self._datum_ids = []

        datum_id = '{}/{}'.format(self._resource_uid,  next(self._datum_counter))
        datum = {'resource': self._resource_uid,
                 'datum_kwargs': {"chunk_num": 0},
                 'datum_id': datum_id}
        self._asset_docs_cache.append(('datum', datum))

        self._datum_ids.append(datum_id)

        return NullStatus()

    def collect(self):
        """
        Record a 'datum' document in the filestore database for each encoder.

        Return a dictionary with references to these documents.
        """
        print('Collect of {} starting'.format(self.name))
        self._ready_to_collect = False

        # Create an Event document and a datum record in filestore for each line
        # in the text file.
        now = ttime.time()
        #ttime.sleep(1)  # wait for file to be written by pizza box
        #breakpoint()
        for datum_id in self._datum_ids:
            data = {self.name: datum_id}
            yield {'data': data,
                   'timestamps': {key: now for key in data},
                   'time': now,
                   'filled': {key: False for key in data}}
        print('Collect of {} complete'.format(self.name))

    def describe_collect(self):
        # TODO Return correct shape (array dims)
        now = ttime.time()
        return {self.name: {self.name:
                     {'filename': self._full_path,
                      'devname': self.dev_name.get(),
                      'source': 'pizzabox-enc-file',
                      'external': 'FILESTORE:',
                      'shape': [-1, -1],
                      'dtype': 'array'}}}


class DigitalOutput(Device):
    """ DigitalOutput """
    enable = Cpt(EpicsSignal, '}Ena-Cmd')
    period_sp = Cpt(EpicsSignal, '}Period-SP')
    unit_sel = Cpt(EpicsSignal, '}Unit-Sel')
    dutycycle_sp = Cpt(EpicsSignal, '}DutyCycle-SP')
    default_pol = Cpt(EpicsSignal, '}Dflt-Sel')

    def __init__(self, *args, reg, **kwargs):
        self._reg = reg
        super().__init__(*args, **kwargs)
        self._ready_to_collect = False
        if self.connected:
            self.enable.put(0)


class DigitalInput(Device):
    """This class defines components but does not implement actual reading.
    See DigitalInputFS """
    data_I = Cpt(EpicsSignal, '}Raw:Data-I_')
    sec_array = Cpt(EpicsSignal, '}T:sec_Bin_')
    nsec_array = Cpt(EpicsSignal, '}T:nsec_Bin_')
    index_array = Cpt(EpicsSignal, '}Cnt:Index_Bin_')
    data_array = Cpt(EpicsSignal, '}Data_Bin_')
    # The '$' in the PV allows us to write 40 chars instead of 20.
    filepath = Cpt(EpicsSignal, '}ID:File.VAL', string=True)
    dev_name = Cpt(EpicsSignal, '}DevName')

    ignore_rb = Cpt(EpicsSignal, '}Ignore-RB')
    ignore_sel = Cpt(EpicsSignal, '}Ignore-Sel')

    def __init__(self, *args, reg, **kwargs):
        self._reg = reg
        super().__init__(*args, **kwargs)
        self._ready_to_collect = False
        if self.connected:
            self.ignore_sel.put(1)


class DIFS(DigitalInput):
    "Encoder Device, when read, returns references to data in filestore."
    chunk_size = 2**20
    write_path_template = '/data/nsls2/qas-new/legacy/raw/pizza_box_data/%Y/%m/%d/'

    def stage(self):
        "Set the filename and record it in a 'resource' document in the filestore database."


        print(self.name, 'stage')
        DIRECTORY = datetime.now().strftime(self.write_path_template)
        #DIRECTORY = "/data/nsls2/qas-new/legacy/raw/pb_data"

        filename = 'di_' + str(uuid.uuid4())[:6]
        self._full_path = os.path.join(DIRECTORY, filename)  # stash for future reference
        print(self._full_path)
        self.filepath.put(self._full_path)
        self.resource_uid = self._reg.register_resource(
            'PIZZABOX_DI_FILE_TXT',
            DIRECTORY, self._full_path,
            {'chunk_size': self.chunk_size})

        super().stage()

    def unstage(self):
        self.ignore_sel.set(1).wait()
        return super().unstage()

    def kickoff(self):
        print('kickoff', self.name)
        self._ready_to_collect = True
        "Start writing data into the file."

        st = self.ignore_sel.set(0)

        # Return a 'status object' that immediately reports we are 'done' ---
        # ready to collect at any time.
        # return NullStatus()
        return st

    def complete(self):
        print('complete', self.name, '| filepath', self._full_path)
        if not self._ready_to_collect:
            raise RuntimeError("must called kickoff() method before calling complete()")
        # Stop adding new data to the file.
        self.ignore_sel.set(1).wait()
        #while not os.path.isfile(self._full_path):
        #    ttime.sleep(.1)
        return NullStatus()

    def collect(self):
        """
        Record a 'datum' document in the filestore database for each encoder.
        Return a dictionary with references to these documents.
        """
        print('collect', self.name)
        self._ready_to_collect = False

        # Create an Event document and a datum record in filestore for each line
        # in the text file.
        now = ttime.time()
        ttime.sleep(1)  # wait for file to be written by pizza box
        if os.path.isfile(self._full_path):
            with open(self._full_path, 'r') as f:
                linecount = len(list(f))
            chunk_count = linecount // self.chunk_size + int(linecount % self.chunk_size != 0)
            for chunk_num in range(chunk_count):
                datum_uid = self._reg.register_datum(self.resource_uid,
                                                     {'chunk_num': chunk_num})
                data = {self.name: datum_uid}

                yield {'data': data,
                       'timestamps': {key: now for key in data}, 'time': now}
        else:
            print('collect {}: File was not created'.format(self.name))
            print("filename : {}", self._full_path)

    def describe_collect(self):
        # TODO Return correct shape (array dims)
        now = ttime.time()
        return {self.name: {self.name:
                     {'filename': self._full_path,
                      'devname': self.dev_name.get(),
                      'source': 'pizzabox-di-file',
                      'external': 'FILESTORE:',
                      'shape': [1024, 5],
                      'dtype': 'array'}}}

class PizzaBoxFS(Device):
    ts_sec = Cpt(EpicsSignal, '}T:sec-I')
    #internal_ts_sel = Cpt(EpicsSignal, '}T:Internal-Sel')

    enc1 = Cpt(EncoderFS, ':1')
    enc2 = Cpt(EncoderFS, ':2')
    enc3 = Cpt(EncoderFS, ':3')
    enc4 = Cpt(EncoderFS, ':4')
    di = Cpt(DIFS, ':DI', reg=db.reg)
    do0 = Cpt(DigitalOutput, '-DO:0', reg=db.reg)
    do1 = Cpt(DigitalOutput, '-DO:1', reg=db.reg)
    do2 = Cpt(DigitalOutput, '-DO:2', reg=db.reg)
    do3 = Cpt(DigitalOutput, '-DO:3', reg=db.reg)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # must use internal timestamps or no bytes are written

    def kickoff(self):
        "Call encoder.kickoff() for every encoder."
        for attr_name in ['enc1', 'enc2', 'enc3', 'enc4']:
            status = getattr(self, attr_name).kickoff()
            print("Eli's test", self.attr_name)
        # it's fine to just return one of the status objects
        return status

    def collect(self):
        "Call encoder.collect() for every encoder."
        # Stop writing data to the file in all encoders.
        for attr_name in ['enc1', 'enc2', 'enc3', 'enc4']:
            getattr(self, attr_name).ignore_sel.set(1).wait()
        # Now collect the data accumulated by all encoders.
        for attr_name in ['enc1', 'enc2', 'enc3', 'enc4']:
            yield from getattr(self, attr_name).collect()

print("init pizza box")
pb1 = PizzaBoxFS('XF:07BM-CT{Enc01', name = 'pb1')
#pb1.enc1.pulses_per_deg = 9400000/360
pb1.enc1.pulses_per_deg=23600*400/360

pb2 = PizzaBoxFS('XF:07BMB-CT{Enc02', name = 'pb2')
print('done')


class TriggerAdc(Device):
    file_size = Cpt(EpicsSignal, '}FileSize')
    reset = Cpt(EpicsSignal, '}Rst-Cmd')
    filepath = Cpt(EpicsSignal, '}ID:File.VAL', string=True)
    sec_array = Cpt(EpicsSignal, '}T:sec_Bin_')
    nsec_array = Cpt(EpicsSignal, '}T:nsec_Bin_')
    #pos_array = Cpt(EpicsSignal, '}Cnt:Pos_Bin_')
    index_array = Cpt(EpicsSignal, '}Cnt:Index_Bin_')
    data_array = Cpt(EpicsSignal, '}Data_Bin_')
    sample_rate = Cpt(EpicsSignal,'}F:Sample-I_', write_pv='}F:Sample-SP')
    enable_averaging = Cpt(EpicsSignal, '}Avrg-Sts', write_pv='}Avrg-Sel')
    averaging_points = Cpt(EpicsSignal, '}Avrg-SP')
    averaging_points_rbv = Cpt(EpicsSignal, '}GP-ADC:Reg0-RB_')
    dev_saturation = Cpt(EpicsSignal, '}DevSat')
    polarity = 'neg'
    # offset = Cpt(EpicsSignal, '}Offset')

    enable_sel = Cpt(EpicsSignal, '}Ena-Sel')
    enable_rb = Cpt(EpicsSignal, '}Ena-Sts')

    def timeout_handler(self, signum, frame):
        print("{}.connected timeout".format(self.name))
        raise Exception("end of time")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ready_to_collect = False

        #signal.signal(signal.SIGALRM, self.timeout_handler)
        #signal.setitimer(signal.ITIMER_REAL, 2)
        #try:
        #    while(self.connected == False):
        #        pass
        if self.connected:
            #self.enable_sel.put(1)
            #self.sample_rate.put(350)
            self.enable_averaging.put(1)
            if self.averaging_points.get() == 0:
                self.averaging_points.put("1024")
        #except Exception as exc:
        #    pass
        #signal.alarm(0)

# needed for dual adc fs, this is the triggering Adc (missing volt and offset)
class Adc(TriggerAdc):
    volt = Cpt(EpicsSignal, '}E-I')
    dev_name = Cpt(EpicsSignal, '}DevName')
    volt_array = Cpt(EpicsSignal, '}V-I')


class AdcFS(Adc):
    "Adc Device, when read, returns references to data in filestore."
    chunk_size = 2**20
    write_path_template = '/data/nsls2/qas-new/legacy/raw/pizza_box_data/%Y/%m/%d/'

    def __init__(self, *args, reg, **kwargs):
        self._reg = reg
        super().__init__(*args, **kwargs)

    def stage(self):
        "Set the filename and record it in a 'resource' document in the filestore database."
        if(self.connected):
            print(self.name, 'stage')
            DIRECTORY = datetime.now().strftime(self.write_path_template)
            #DIRECTORY = "/data/nsls2/qas-new/legacy/raw/pb_data"

            filename = 'an_' + str(uuid.uuid4())[:6]
            self._full_path = os.path.join(DIRECTORY, filename)  # stash for future reference
            print("writing to {}".format(self._full_path))

            self.filepath.put(self._full_path)
            self.resource_uid = self._reg.register_resource(
                'PIZZABOX_AN_FILE_TXT',
                DIRECTORY, self._full_path,
                {'chunk_size': self.chunk_size})

            super().stage()
        else:
            print("{} not staged".format(self.name))

    def unstage(self):
        if self.connected:
            self.enable_sel.set(1).wait()
            return super().unstage()

    def kickoff(self):
        print('kickoff', self.name)
        self._ready_to_collect = True
        "Start writing data into the file."

        st = self.enable_sel.set(0)

        # Return a 'status object' that immediately reports we are 'done' ---
        # ready to collect at any time.
        # return NullStatus()
        return st

    def complete(self):
        print('complete', self.name, '| filepath', self._full_path)
        if not self._ready_to_collect:
            raise RuntimeError("must called kickoff() method before calling complete()")
        # Stop adding new data to the file.
        self.enable_sel.set(1).wait()
        return NullStatus()

    def collect(self):
        """
        Record a 'datum' document in the filestore database for each encoder.

        Return a dictionary with references to these documents.
        """
        print('collect', self.name)
        self._ready_to_collect = False

        # Create an Event document and a datum record in filestore for each line
        # in the text file.
        now = ttime.time()
        ttime.sleep(1)  # wait for file to be written by pizza box
        if os.path.isfile(self._full_path):
            with open(self._full_path, 'r') as f:
                linecount = 0
                for ln in f:
                    linecount += 1

            chunk_count = linecount // self.chunk_size + int(linecount % self.chunk_size != 0)
            for chunk_num in range(chunk_count):
                datum_uid = self._reg.register_datum(self.resource_uid,
                                                     {'chunk_num': chunk_num})
                data = {self.name: datum_uid}

                yield {'data': data,
                       'timestamps': {key: now for key in data},
                       'time': now,
                       'filled': {key: False for key in data}}
        else:
            print('collect {}: File was not created'.format(self.name))
            print("filename : {}".format(self._full_path))

    def describe_collect(self):
        # TODO Return correct shape (array dims)
        now = ttime.time()
        return {self.name: {self.name:
                     {'filename': self._full_path,
                      'devname': self.dev_name.get(),
                      'source': 'pizzabox-adc-file',
                      'external': 'FILESTORE:',
                      'shape': [5,],
                      'dtype': 'array'}}}


class DualAdcFS(TriggerAdc):
    '''
    Adc Device, when read, returns references to data in filestore.
        This is for a dual device. It defines one ADC which
            uses a shared triggering mechanism for file writing.
        The adc is either a 'master' or 'slave'. If 'master', then kickoff()
            should trigger the 'Ena-Sel' PV (which starts collecting data to file).
        If 'slave', then it should check that the 'Ena-Sel' PV is set.
        TODO : Need to add a good waiting mechanism for this.
    '''
    # these are for the dual ADC FS
    # column is the column and enable_sel is what triggers the collection
    # rename because of existing children pv's
    chunk_size = 2**20
    write_path_template = '/data/nsls2/qas-new/legacy/raw/pizza_box_data/%Y/%m/%d/'
    volt = FC(EpicsSignal, '{self._adc_read}}}E-I')
    offset = FC(EpicsSignal, '{self._adc_read}}}Offset')
    dev_name = FC(EpicsSignal, '{self._adc_read}}}DevName')

    def __init__(self, *args, adc_column, adc_read_name, twin_adc=None,
                 **kwargs):
        '''
            This is for a dual ADC system.
            adc_column : the column
            adc_trigger: the adc pv used for triggering for this dual channel
            mode : {'master', 'slave'}
                The mode. Master will create a new file and resource during kickoff
                    Slave assumes the new file and resource are already created.
                    Slave should check if acquisition has been triggered first,
                    else return an error.

            Notes:
                The adc master and adc for triggering are not necessarily the same
                    (for ex, adc6 and adc7 triggered using adc1, but adc6 is
                     what will put to adc1's trigger)
        '''
        self._asset_docs_cache = deque()
        self._full_path = ''
        self._resource_uid = None
        self._datum_counter = None
        self._twin_adc = twin_adc
        self._column = adc_column
        self._adc_read = adc_read_name
        self._staged_adc = False
        self._kickoff_adc = False
        self._complete_adc = False
        super().__init__(*args, **kwargs)
        self._data_docs_cache = deque()
        self._in_fly_code = False

    def collect_asset_docs(self):
        if not self._in_fly_code:
            return
        self.generate_those_documents()
        items = list(self._asset_docs_cache)
        print(f"DOCS!!! for DualAdcFS {self}", items)
        self._asset_docs_cache.clear()
        for item in items:
            yield item
        self._in_fly_code = False

    def stage(self):
        "Set the filename and record it in a 'resource' document in the filestore database."

        self._in_fly_code = False

        if self.connected:
            # NOTE: master MUST be done before slave. need to fix this later
            if self._twin_adc is None:
                raise ValueError("Error a twin ADC must be given")

            # if twin didnt stage yet, stage
            if not self._twin_adc._staged_adc:
                self._datum_counter = itertools.count()
                self._staged_adc = True

                print(self.name, 'stage')
                filename = 'an_' + str(uuid.uuid4())[:6]
                write_path_template = os.path.join('pizza_box_data/%Y/%m/%d', filename)
                resource_path = datetime.now().strftime(write_path_template)
                filepath = os.path.join(ROOT_PATH, RAW_FILEPATH, resource_path)
                self._full_path = filepath

                print(">>>>>>>>>>>>>>> writing to {}".format(self._full_path))

                self.filepath.put(self._full_path)
                self._resource_uid = str(uuid.uuid4())
                resource = {'spec' : 'PIZZABOX_AN_FILE_TXT',
                            'root' : os.path.join(ROOT_PATH, RAW_FILEPATH),
                            'resource_path': resource_path,
                            'resource_kwargs': {'chunk_size': self.chunk_size},
                            'path_semantics': {'posix': 'posix', 'nt': 'windows'}[os.name],
                            'uid': self._resource_uid}
                print("RESOURCE!!!!!!!!!!!", resource)
                self._asset_docs_cache.append(('resource', resource))
                print('Staging of {} complete'.format(self.name))
     
                super().stage()
            else:
                self._datum_counter = self._twin_adc._datum_counter
                # don't stage, use twin's info
                self._resource_uid = self._twin_adc._resource_uid
                self._full_path = self._twin_adc._full_path
                # reset twin
                self._twin_adc._staged_adc = False
                print("ACD {}'s twin {} already staged. File path already set to {}".format(self.name, self._twin_adc.name, self.filepath.get()))
        else:
            msg = "Error, adc {} not ready for acquiring\n".format(self.name)
            raise ValueError(msg)
        time.sleep(.1)


    def unstage(self):
        if self.connected:
            self.enable_sel.set(1).wait()
            # either master or slave can unstage if needed, safer
            self._staged_adc = False
            self._kickoff_adc = False
            self._complete_adc = False
            self._datum_counter = None
            return super().unstage()

    def kickoff(self):
        print('==' * 70)
        print('kickoff', self.name)
        print('==' * 59)
        if self._twin_adc is None:
            raise ValueError("ADC must have a twin")

        if self._twin_adc._kickoff_adc is False:
            self._ready_to_collect = True
            "Start writing data into the file."
       
            st = self.enable_sel.set(0)
            self._kickoff_adc = True
            return st
        else:
            print("ADC {} was kicked off by {} already".format(self.name, self._twin_adc.name))
            self._ready_to_collect = True
            #reset kickoff
            self._kickoff_adc = False
            #reset twin
            self._twin_adc._kickoff_adc = False
            st = Status()
            st._finished()
            return st

    def generate_those_documents(self):
       
        now = ttime.time()
        #ttime.sleep(1)  # wait for file to be written by pizza box
        #if os.path.isfile(self._full_path):
        for _ in range(5):
            print(f'trying to open {self._full_path} round {_}')
            try:
                with open(self._full_path, 'r') as f:
                    linecount = 0
                    for ln in f:
                        linecount += 1
            except FileNotFoundError:
                time.sleep(1)
                continue
            break
        else:
            raise FileNotFoundError(self._full_path)
        chunk_count = linecount // self.chunk_size + int(linecount % self.chunk_size != 0)
        for chunk_num in range(chunk_count):
    
            datum_id = '{}/{}'.format(self._resource_uid,  next(self._datum_counter))
            datum = {'resource': self._resource_uid,
                     'datum_kwargs': {'chunk_num': chunk_num,
                                      'column' : self._column},
                     'datum_id': datum_id}
            self._asset_docs_cache.append(('datum', datum))
            data = {self.name: datum_id}
            self._data_docs_cache.append(data)

    def complete(self):
        
        print('complete', self.name, '| filepath', self._full_path)
        if not self._ready_to_collect:
            raise RuntimeError("must called kickoff() method before calling complete()")
        
        if self._twin_adc._complete_adc is False:
            # Stop adding new data to the file.
            self.enable_sel.put(1)
            self._complete_adc = True
        else:
            print("Device already stopped by {}".format(self._twin_adc.name))
            self._twin_adc._complete_adc = False
            self._complete_adc = False

        status = DeviceStatus(self)
        from threading import Timer
        # wait on this complete function for 1 second
        # hold on to the Timer so it will not be garbage collected
        self.complete_timer = Timer(1, status.set_finished)
        self.complete_timer.start()
        return status

    def collect(self):
        """
        Record a 'datum' document in the filestore database for each encoder.
        Return a dictionary with references to these documents.
        """
        print('Collect of {} starting'.format(self.name))
        self._ready_to_collect = False

        # Create an Event document and a datum record in filestore for each line
        # in the text file.
        now = ttime.time()
        #ttime.sleep(1)  # wait for file to be written by pizza box
        #if os.path.isfile(self._full_path):
        #    with open(self._full_path, 'r') as f:
        #        linecount = 0
        #        for ln in f:
        #            linecount += 1
            #breakpoint()
            #chunk_count = linecount // self.chunk_size + int(linecount % self.chunk_size != 0)
            #for chunk_num in range(chunk_count):
            #
            #    datum_id = '{}/{}'.format(self._resource_uid,  next(self._datum_counter))
            #    datum = {'resource': self._resource_uid,
            #             'datum_kwargs': {'chunk_num': chunk_num,
            #                               'column' : self._column},
            #             'datum_id': datum_id}
            #    self._asset_docs_cache.append(('datum', datum))
#    data = {self.name: datum_id}
        print(f"DualAdcFS.collect: {len(self._data_docs_cache)}")
        for data in self._data_docs_cache:
            yield {'data': data,
                       'timestamps': {key: now for key in data}, 'time': now}
        
        self._data_docs_cache.clear()
        self._in_fly_code = True
        #else:
        #    print('collect {}: File was not created'.format(self.name))
        #    print("filename : {}".format(self._full_path))

    def describe_collect(self):
        # TODO Return correct shape (array dims)
        now = ttime.time()
        return {self.name: {self.name:
                     {'filename': self._full_path,
                      'devname': self.dev_name.get(),
                      'source': 'pizzabox-adc-file',
                      'external': 'FILESTORE:',
                      'shape': [5,],
                      'dtype': 'array'}}}


class PizzaBoxAnalogFS(Device):
    #internal_ts_sel = Cpt(EpicsSignal, 'Gen}T:Internal-Sel')

    adc1 = Cpt(AdcFS, 'ADC:1', reg=db.reg)
    adc6 = Cpt(AdcFS, 'ADC:6', reg=db.reg)
    adc7 = Cpt(AdcFS, 'ADC:7', reg=db.reg)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # must use internal timestamps or no bytes are written
        # self.stage_sigs[self.internal_ts_sel] = 1

    def kickoff(self):
        "Call encoder.kickoff() for every encoder."
        for attr_name in ['adc1']: #, 'adc2', 'adc3', 'adc4']:
            status = getattr(self, attr_name).kickoff()
        # it's fine to just return one of the status objects
        return status

    def collect(self):
        "Call adc.collect() for every encoder."
        # Stop writing data to the file in all encoders.
        for attr_name in ['adc1']: #, 'adc2', 'adc3', 'adc4']:
            getattr(self, attr_name).enable_sel.set(0).wait()
        # Now collect the data accumulated by all encoders.
        for attr_name in ['adc1']: #, 'adc2', 'adc3', 'adc4']:
            yield from getattr(self, attr_name).collect()


# the 2 channel pizza box, uncomment to use (and comment out 6 channel)
#pba1 = PizzaBoxAnalogFS('XF:07BMB-CT{GP1-', name = 'pba1')
# set the PV's that are 'i0', 'it' and 'ir' (if any)
#pba1.adc6.dev_name.put('i0')
#pba1.adc7.dev_name.put('it')

class PizzaBoxDualAnalogFS(Device):
    #internal_ts_sel = Cpt(EpicsSignal, 'Gen}T:Internal-Sel')

    # for these, you need a master and a slave
    # set the PV that will always trigger to master and any additional to slave
    # first pair
    '''
        Some comments about defining these adc's for the pizza boxes:
            adc_column: int
                this is the column in the file that the data is written
                0, being the first column with encoder data
            adc_read_name : str
                This is the PV string for the Epics PV we must read from 
            mode: {'master', 'slave', 'disabled'}
                This is the mode.
                In slave mode, the adc won't trigger the collection.
                In disabled mode, the adc won't stage when the parent stage() method
                    is called.
                In master mode, the adc will trigger the collection of data.
                If you use just one PV in a pair, make sure it is in 'master' mode.
                If you use both PV's in a pair, make sure only one is set to "master"
                Another option is we could remove this option and just have
                each PV check if the collection has been triggered and trigger
                otherwise.

        An alternative to defining these is to create an object per pair of ADC's.
        However, this is not backwards compatible with the way iss runs on the
        pizza boxes. Some care must be taken to modify the plans and the GUI if
        doing this.
    '''
    adc3 = Cpt(DualAdcFS, 'ADC:1',
               adc_column=0, adc_read_name="XF:07BMB-CT{GP2-ADC:3")
    adc4 = Cpt(DualAdcFS, 'ADC:1',
               adc_column=1, adc_read_name="XF:07BMB-CT{GP2-ADC:4")

    # second pair
    # if using both, one must be master, the other slave
    adc5 = Cpt(DualAdcFS, 'ADC:6',
               adc_column=0, adc_read_name="XF:07BMB-CT{GP2-ADC:5")
    adc6 = Cpt(DualAdcFS, 'ADC:6',
               adc_column=1, adc_read_name="XF:07BMB-CT{GP2-ADC:6")

    # third pair
    adc7 = Cpt(DualAdcFS, 'ADC:7',
               adc_column=0, adc_read_name="XF:07BMB-CT{GP2-ADC:7")
    adc8 = Cpt(DualAdcFS, 'ADC:7',
               adc_column=1, adc_read_name="XF:07BMB-CT{GP2-ADC:8")



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # must use internal timestamps or no bytes are written
        # self.stage_sigs[self.internal_ts_sel] = 1

    def _get_active_devices(self):
        devices = [getattr(self, name) for name in self.component_names]
        devices = [device for device in devices if device._mode != 'disabled']
        return devices

    def stage(self):
        devices = self._get_active_devices()
        for device in devices:
            device.stage()

    def unstage(self):
        devices = self._get_active_devices()
        for device in devices:
            device.unstage()

    def kickoff(self):
        '''Call encoder.kickoff() for every encoder.

            This is untested. Currently isstools uses the underlying adc
                children.
        '''
        devices = self._get_active_devices()
        compound_status = None
        for device in devices:
            new_status = device.kickoff()
            if compound_status is None:
                new_status = compound_status
            else:
                new_status = ophyd.AndStatus(compound_status, new_status)
        return new_status

    def complete(self):
        '''Call encoder.complete() for every encoder.

            This is untested. Currently isstools uses the underlying adc
                children.
        '''
        devices = self._get_active_devices()
        compound_status = None
        for device in devices:
            new_status = device.complete()
            if compound_status is None:
                new_status = compound_status
            else:
                new_status = ophyd.AndStatus(compound_status, new_status)
        return new_status

    def collect(self):
        "Call adc.collect() for every encoder."
        devices = self._get_active_devices()
        for device in devices:
            yield from device.collect()

    def collect_asset_docs(self):
        print(f"PizzaBox collect_asset_docs")
        devices = self._get_active_devices()
        for device in devices:
            yield from device.collect_asset_docs()


print("init 6 chan pizza box")
# the 6 channel pizza box
pba1 = PizzaBoxDualAnalogFS('XF:07BMB-CT{GP2-', name = 'pba1')

# twin adc is the other adc
pba1.adc3._twin_adc = pba1.adc4
pba1.adc3._mode = "enabled"

pba1.adc4._twin_adc = pba1.adc3
pba1.adc4._mode = "enabled"

pba1.adc5._twin_adc = pba1.adc6
pba1.adc5._mode = "enabled"

pba1.adc6._twin_adc = pba1.adc5
pba1.adc6._mode = "enabled"

pba1.adc7._twin_adc = pba1.adc8
pba1.adc7._mode = "enabled"

pba1.adc8._twin_adc = pba1.adc7
pba1.adc8._mode = "enabled"

# set the PV's that are 'i0', 'it' and 'ir' (if any)
pba1.adc3.dev_name.put('i0')
pba1.adc4.dev_name.put('it')
pba1.adc5.dev_name.put('ir')
pba1.adc6.dev_name.put('pips')
pba1.adc7.dev_name.put('adc7')
pba1.adc8.dev_name.put('adc8')
print("done")

# the 6 channel pizza box
#pba1_6chan = PizzaBoxAnalogFS('XF:07BMB-CT{GP2-', name = 'pba1_6chan')
# set the PV's that are 'i0', 'it' and 'ir' (if any)
#pba1_6chan.adc6.dev_name.put('i0')
#pba1_6chan.adc7.dev_name.put('it')

# the 6 channel pizza box
#pba1 = PizzaBoxAnalogFS('XF:07BMB-CT{GP2-', name = 'pba1')
# set the PV's that are 'i0', 'it' and 'ir' (if any)
#pba1.adc6.dev_name.put('i0')
#pba1.adc7.dev_name.put('it')

# cludge for now
