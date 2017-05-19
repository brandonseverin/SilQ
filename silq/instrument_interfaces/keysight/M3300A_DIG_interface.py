from silq.instrument_interfaces import InstrumentInterface, Channel
from silq.meta_instruments.layout import SingleConnection, CombinedConnection
from silq.pulses.pulse_types import TriggerPulse

from qcodes.utils import validators as vals
from qcodes import ManualParameter
from qcodes.instrument_drivers.keysight.SD_common.SD_acquisition_controller import *
from qcodes.instrument_drivers.keysight.M3300A import M3300A_DIG as dig_driver


class M3300A_DIG_Interface(InstrumentInterface):
    def __init__(self, instrument_name, acquisition_controller_names=[], **kwargs):
        super().__init__(instrument_name, **kwargs)
        self._pulse_sequence.allow_untargeted_pulses = True

        # Initialize channels
        self._acquisition_channels  = {
            'ch{}'.format(k): Channel(instrument_name=self.instrument_name(),
                                      name='ch{}'.format(k), input=True)
            for k in range(8)
            }

        self._channels = {
            **self._acquisition_channels ,
            'trig_in': Channel(instrument_name=self.instrument_name(),
                               name='trig_in', input=True),
        }

        # Organize acquisition controllers
        self.acquisition_controllers = {}
        for acquisition_controller_name in acquisition_controller_names:
            self.add_acquisition_controller(acquisition_controller_name)

        self.add_parameter(name='default_acquisition_controller',
                           parameter_class=ManualParameter,
                           initial_value='None',
                           vals=vals.Enum(None,
                               'None', *self.acquisition_controllers.keys()))

        self.add_parameter(name='acquisition_controller',
                           parameter_class=ManualParameter,
                           vals=vals.Enum(
                               'None', *self.acquisition_controllers.keys()))

        # Names of acquisition channels [chA, chB, etc.]
        self.add_parameter(name='acquisition_channels',
                           parameter_class=ManualParameter,
                           initial_value=[],
                           vals=vals.Anything())
        # Set up the driver to a known default state
        self.initialize_driver()

    @property
    def _acquisition_controller(self):
        return self.acquisition_controllers.get(
            self.acquisition_controller(), None)

    # Make all parameters of the interface transparent to the acquisition controller
    @property
    def acquisition(self):
        """
        Return:
            The acquisition parameter in the current interface
        """
        return self._acquisition_controller.acquisition

    @property
    def samples(self):
        """
        Return:
            The samples_per_record parameter in the current interface
        """
        return self._acquisition_controller.samples_per_record

    @property
    def trigger_channel(self):
        """
        Return:
            The trigger_channel parameter in the current interface
        """
        return self._acquisition_controller.trigger_channel

    @property
    def trigger_edge(self):
        """
        Return:
            The trigger_edge parameter in the current interface
        """
        return self._acquisition_controller.trigger_edge

    @property
    def trigger_threshold(self):
        return self._acquisition_controller.trigger_threshold

    @property
    def sample_rate(self):
        return self._acquisition_controller.sample_rate

    def add_acquisition_controller(self, acquisition_controller_name,
                                   cls_name=None):
        """
        Adds an acquisition controller to the available controllers.
        If another acquisition controller exists of the same class, it will
        be overwritten.
        Args:
            acquisition_controller_name: instrument name of controller.
                Must be on same server as interface and Keysight digitizer
            cls_name: Optional name of class, which is used as controller key.
                If no cls_name is provided, it is found from the instrument
                class name

        Returns:
            None
        """
        acquisition_controller = self.find_instrument(
            acquisition_controller_name)
        if cls_name is None:
            cls_name = acquisition_controller.__class__.__name__
        # Remove _Controller from cls_name

        cls_name = cls_name.replace('_Controller', '')

        self.acquisition_controllers[cls_name] = acquisition_controller

    def initialize_driver(self):
        """
            Puts driver into a known initial state. Further configuration will
            be done in the configure_driver and get_final_additional_pulses
            functions.
        """
        for k in range(8):
            self.instrument.parameters['impedance_{}'.format(k)].set(1) # 50 Ohm impedance
            self.instrument.parameters['coupling_{}'.format(k)].set(0)  # DC Coupled
            self.instrument.parameters['full_scale_{}'.format(k)].set(3.0)  # 3.0 Volts
        self.acquisition_controller().initialize_driver()

    def configure_driver(self):
        """ Configures the underlying driver using interface parameters

            Args:
                None
            Return: 
                None
        """
        controller = self._acquisition_controller
        # Acquire on all channels
        controller.channel_selection = [x for x in range(8)]
        if controller() == 'Triggered':
            # TODO: Read connections to figure out where to trigger from
            controller.trigger_channel(4)
            controller.trigger_edge(1)
            controller.trigger_threshold(0.5)
            controller.sample_rate(1e6)
    
        # Check what averaging mode is needed by each pulse            
        if any(self._pulse_sequence.get_pulses(average='none')):
            controller.average_mode('none')
        else:
            controller.average_mode('trace')


    def get_final_additional_pulses(self, **kwargs):
        if not self._pulse_sequence.get_pulses(acquire=True):
            # No pulses need to be acquired
            return []
        elif self.average_mode() == 'none':
            # Add a single trigger pulse when starting acquisition
            t_start = min(pulse.t_start for pulse in
                          self._pulse_sequence.get_pulses(acquire=True))
            t_stop = max(pulse.t_stop for pulse in
                         self._pulse_sequence.get_pulses(acquire=True))
            t_final = max(pulse.t_stop for pulse in
                          self._pulse_sequence.get_pulses())

            T = t_stop - t_start
            # Capture maximum number of samples on all channels
            for k in range(8):
                self.instrument.parameters['n_points_{}'.format(k)].set(int(T * self.sample_freq))
                # Set an acquisition timeout to be 10% after the last pulse finishes.
                self.instrument.parameters['timeout_{}'.format(k)].set(int(t_final * 1.1))

            acquisition_pulse = \
                TriggerPulse(t_start=t_start,
                             connection_requirements={
                                 'input_instrument': self.instrument_name(),
                                 'trigger': True})
            return [acquisition_pulse]

    def setup(self, **kwargs):
        pass
        # for param in self._used_params:

    def start(self):
        self.instrument.daq_flush_multiple(2 ** 9 - 1)
        self.instrument.daq_start_multiple(2 ** 9 - 1)

    def acquire(self):
        data = {}
        # Split data into pulse traces
        for pulse in self._pulse_sequence.get_pulses(acquire=True):
            data[pulse.name] = {}
            ts = (pulse.t_start, pulse.t_stop)
            sample_range = [int(t * self.sample_freq) for t in ts]
            for ch in range(8):
                ch_data = self.daq_read(ch)
                # Extract acquired data from the channel data
                data[pulse.name][ch] = ch_data[sample_range]
        return data

    def stop(self):
        pass

