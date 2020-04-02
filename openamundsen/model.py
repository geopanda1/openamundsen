from . import conf
from . import dataio
from . import meteo
from . import modelinit
from . import util


def time_step_loop(model):
    for date in model.dates:
        model.logger.info(f'Processing time step {date}')
        meteo.interpolate_station_data(model, date)
        meteo.process_meteo_data(model)
        model_interface(model)
        dataio.update_field_outputs(model)
        dataio.update_point_outputs(model)


def model_interface(model):
    model.logger.debug('Modifying sub-canopy meteorology')
    model.logger.debug('Updating snow albedo')
    model.logger.debug('Adding fresh snow')
    model.logger.debug('Calculating canopy interception')
    model.logger.debug('Calculating melt')


class Model:
    def __init__(self, config):
        self.logger = None
        self.config = None
        self.state = None
        self.dates = None

        modelinit.initialize_logger(self)
        conf.apply_config(self, config)

    def initialize(self):
        self.dates = modelinit.prepare_time_steps(self.config)
        modelinit.initialize_model_grid(self)
        modelinit.initialize_state_variables(self)

        dataio.read_input_data(self)
        self.meteo = dataio.read_meteo_data(self)

    def run(self):
        time_step_loop(self)
