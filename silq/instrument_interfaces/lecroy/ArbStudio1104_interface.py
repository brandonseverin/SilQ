from silq.instrument_interfaces import InstrumentInterface, Channel
from silq.meta_instruments.layout import SingleConnection, CombinedConnection
from silq.pulses import DCPulse, TriggerPulse, PulseImplementation

from qcodes.instrument.parameter import ManualParameter

class ArbStudio1104Interface(InstrumentInterface):
    def __init__(self, instrument_name, **kwargs):
        super().__init__(instrument_name, **kwargs)

        self._output_channels = {
            'ch{}'.format(k): Channel(instrument_name=self.name,
                                      name='ch{}'.format(k), id=k,
                                      output=True) for k in [1, 2, 3, 4]}
        self._trigger_in_channel = Channel(instrument_name=self.name,
                                          name='trig_in',
                                          input_trigger=True)
        self._trigger_out_channel = Channel(instrument_name=self.name,
                                           name='trig_out',
                                           output_TTL=(0, 3.3))
        # TODO check Arbstudio output TTL high

        self._channels = {**self._output_channels,
                         'trig_in': self._trigger_in_channel,
                         'trig_out': self._trigger_out_channel}

        self.pulse_implementations = [
            # TODO implement SinePulse
            # SinePulse(
            #     pulse_requirements=('frequency', {'min':1e6, 'max':50e6})
            # ),
            DCPulseImplementation(
                pulse_requirements=[('amplitude', {'min': -2.5, 'max': 2.5})]
            ),
            TriggerPulseImplementation(
                pulse_requirements=[]
            )
        ]

        self.add_parameter('trigger_in_duration',
                           parameter_class=ManualParameter,
                           units='us',
                           initial_value=0.1)

    def setup(self):
        # TODO implement setup for modes other than stepped
        # Transform into set to ensure that elements are unique
        self.active_channels = []
        for pulse in self.pulse_sequence():
            output = pulse.connection.output
            self.active_channels.append(output['channel'].name)
        self.active_channels = list(set(self.active_channels))

        # # Find sampling rates (these may be different for different channels)
        # sampling_rates = [self.instrument.sampling_rate /
        #                   eval("self.instrument.ch{}_sampling_rate_prescaler()"
        #                        "".format(ch)) for ch in self.active_channels]

        # Generate waveforms and sequences
        self.generate_waveforms()
        self.generate_sequences()

        for channel in self.active_channels:

            eval("self.instrument.{ch}_trigger_source('fp_trigger_in')".format(
                ch=channel))
            eval("self.instrument.{ch}_trigger_mode('stepped')".format(
                ch=channel))
            eval('self.instrument.{ch}_clear_waveforms()'.format(
                ch=channel))

            # Add waveforms to channel
            for waveform in self.waveforms[channel]:
                eval('self.instrument.{ch}_add_waveform({waveform})'.format(
                    ch=channel, waveform=waveform))

            # Add sequence to channel
            eval('self.instrument.{ch}_sequence({sequence})'.format(
                ch=channel, sequence=self.sequences[channel]))

        active_channels_id = [self._channels[channel].id
                              for channel in self.active_channels]
        self.instrument.load_waveforms(channels=active_channels_id)
        self.instrument.load_sequence(channels=active_channels_id)

    def start(self):
        pass

    def stop(self):
        pass

    def get_final_additional_pulses(self):
        return []

    def generate_waveforms(self):
        # Set time t_pulse to zero for each channel
        # This will increase as we iterate over pulses, and is used to ensure
        # that there are no times between pulses
        t_pulse = {ch: 0 for ch in self.active_channels}

        self.waveforms = {ch: [] for ch in self.active_channels}
        for pulse in self.pulse_sequence():

            channels_waveform = pulse.implement()

            for ch, waveform in channels_waveform.items():
                assert pulse.t_start == t_pulse[ch], \
                    "Pulse {}: pulses.t_start = {} does not match {}".format(
                        pulse, pulse.t_start, t_pulse[ch])

                self.waveforms[ch].append(waveform)
                # Increase t_pulse to match start of next pulses
                t_pulse[ch] += pulse.duration
        return self.waveforms

    def generate_sequences(self):
        self.sequences = {ch: range(len(self.waveforms[ch]))
                          for ch in self.active_channels}
        return self.sequences


class DCPulseImplementation(DCPulse, PulseImplementation):
    def __init__(self, **kwargs):
        PulseImplementation.__init__(self, pulse_class=DCPulse, **kwargs)

    def target_pulse(self, pulse, interface, is_primary=False, **kwargs):
        targeted_pulse = PulseImplementation.target_pulse(
            self, pulse, interface=interface, is_primary=is_primary, **kwargs)

        # Check if there are already trigger pulses
        trigger_pulses = interface.input_pulse_sequence().get_pulses(
            t_start=pulse.t_start, trigger=True
        )

        if not is_primary and not trigger_pulses:
            targeted_pulse.additional_pulses.append(
                TriggerPulse(t_start=pulse.t_start,
                             duration=interface.trigger_in_duration(),
                             connection_requirements={
                                 'input_instrument':
                                     interface.instrument_name(),
                                 'trigger': True}
                             )
            )
        return targeted_pulse

    def implement(self):
        """
        Implements the DC pulses for the ArbStudio for SingleConnection and
        CombinedConnection. For a CombinedConnection, it weighs the DC pulses
        amplitude by the corresponding channel scaling factor (default 1).
        Args:

        Returns:
            {output_channel: pulses arr} dictionary for each output channel
        """
        # Arbstudio requires a minimum of four points to be returned
        if isinstance(self.connection, SingleConnection):
            return {self.connection.output['channel'].name:
                        [self.amplitude] * 4}
        elif isinstance(self.connection, CombinedConnection):
            return {ch.name: [self.amplitude] * 4
                    for ch in self.connection.output['channels']}
        else:
            raise Exception("No implementation for connection {}".format(
                self.connection))


class TriggerPulseImplementation(TriggerPulse, PulseImplementation):
    def __init__(self, **kwargs):
        PulseImplementation.__init__(self, pulse_class=TriggerPulse, **kwargs)

    def target_pulse(self, pulse, interface, is_primary=False, **kwargs):
        targeted_pulse = PulseImplementation.target_pulse(
            self, pulse, interface=interface, is_primary=is_primary, **kwargs)
        if not is_primary:
            targeted_pulse.additional_pulses.append(
                TriggerPulse(t_start=pulse.t_start,
                             duration=interface.trigger_in_duration(),
                             connection_requirements={
                                 'input_instrument':
                                     interface.instrument_name(),
                                 'trigger': True}
                             )
            )
        return targeted_pulse