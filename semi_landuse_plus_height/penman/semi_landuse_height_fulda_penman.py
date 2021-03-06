# -*- coding: utf-8 -*-
"""
Created on Nov 29 13:46 2017
@author(s): Florian U. Jehn
"""
from cell_template import CellTemplate
import cmf
import datetime
import os
import numpy as np
import spotpy
from dateutil.relativedelta import relativedelta


class SemiDisLanduse:
    def __init__(self, begin: datetime.datetime, end: datetime.datetime,
                 subcatchment_names):
        """

        :param begin:
        :param end:
        """
        project = cmf.project()
        # Add outlet
        self.outlet = project.NewOutlet("Outlet", 50, 0, 0)
        self.project = project
        self.begin = begin
        self.end = end
        self.subcatchment_names = subcatchment_names
        self.dis_eval, self.subcatchments = self.load_data()
        self.params = self.create_params()
        self.cell_list = self.create_cells()
        cmf.set_parallel_threads(1)

    def create_cells(self):
        """
        Creates a cell for every subcatchment and stores them in a list.

        :return: cell_list: List of all cells, so they are more easily
        callable
        """
        cell_list = []
        for sub in self.subcatchments:
            new_cell = CellTemplate(self.project, self.subcatchments[sub],
                                    sub, self.outlet)
            cell_list.append(new_cell)
        return cell_list

    def set_parameters(self, params):
        """
        Initializes all cells with the parameters provided

        :return: None
        """
        for cell in self.cell_list:
            cell.set_parameters(params)

    def load_data(self):
        """

        :return:
        """
        # Size of all subcatchments km²
        sizes = {"crops_high": 13.009483985765122,
                 "grass_high": 48.03501779359431,
                 "wood_high": 79.05763345195729,
                 "rest_high": 1.000729537366548,
                 "crops_low": 134.09775800711745,
                 "grass_low": 103.07514234875444,
                 "wood_low": 136.09921708185053,
                 "rest_low": 48.03501779359431}

        # Average height of all subcatchments
        heights = {"crops_high": 535.760692308,
                   "grass_high": 582.983291667,
                   "wood_high": 633.839075949,
                   "rest_high": 673.214,
                   "crops_low": 346.971231343,
                   "grass_low": 372.699019417,
                   "wood_low": 388.314742647,
                   "rest_low": 311.424604167}

        # Different input data types (except discharge)
        input_data = ["T_avg", "T_min", "T_max", "prec", "wind", "sunshine",
                      "rel_hum"]

        # Read in the data for all subcatchments separately
        subcatchments = {}
        for sub in self.subcatchment_names:
            subcatchments[sub] = {"size": sizes[sub]}
            subcatchments[sub]["height"] = heights[sub]
            subcatchments[sub]["data"] = {}

            for data_type in input_data:
                name = data_type + "_kaemmerzell_" + sub + "_79_89.txt"
                timeseries = self.read_timeseries(name)
                subcatchments[sub]["data"][data_type] = timeseries

        dis_eval = self.read_timeseries("dis_eval_kaemmerzell_79_89.txt",
                                        convert=True)

        return dis_eval, subcatchments

    def read_timeseries(self, timeseries_name, convert=False):
        """
        Loads in a timeseries and returns it

        :param timeseries_name:
        :param convert: Discharge needs to be converted.

        :return: timeseries
        """
        # Fixed model starting point
        # Change this if you want a warm up period other than a year
        begin = self.begin - relativedelta(years=1)
        step = datetime.timedelta(days=1)

        timeseries = cmf.timeseries(begin, step)
        timeseries.extend(float(value.strip("\n")) for value in open(
            timeseries_name))

        # Converts the discharge from m3/sec to mm
        if convert:
            area_catchment = 562.41
            timeseries *= 86400 * 1e3 / (area_catchment * 1e6)

        return timeseries

    @staticmethod
    def create_params():
        """
        Creates all the parameters needed.

        :return: List of parameters
        """
        param = spotpy.parameter.Uniform
        params = [param('tr_soil_gw', 1., 400.),
                  # tr_soil_out = residence time from soil to outlet
                  param("tr_soil_out", 1., 200.),
                  # tr_GW_out = Residence time in the groundwater to
                  #  the outlet
                  param('tr_gw_out', 1., 650.),
                  # V0_soil = field capacity for the soil
                  param('V0_soil', 1., 300.),
                  # param("V0_gw", 1, 300.),
                  # beta_soil_GW = Changes the flux curve of the soil
                  # to the groundwater
                  param('beta_soil_gw', 0.5, 6.0),
                  # beta_soil_out = exponent that changes the form of the
                  # flux from the soil to the outlet
                  param("beta_soil_out", 0.5, 7.0),
                  # ETV1 = the Volume that defines that the evaporation
                  # is lowered because of not enough water in the soil
                  param('ETV1', 1., 300.),
                  # fETV0 = factor the ET is multiplied by, when water is
                  #  low
                  param('fETV0', 0.1, 0.9),
                  # Rate of snow melt (for the low region)
                  param('meltrate', 0.01, 12.),
                  # Snow_melt_temp = Temperature at which the snow melts
                  # (needed because of averaged temp (for the low region)
                  param('snow_melt_temp', -3.0, 3.0),
                  # LAI = leaf area index
                  param('LAI', 1., 12),
                  # Canopy Closure
                  param("CanopyClosure", 0.1, 0.9)
                  ]
        return params

    def run_model(self):
        """
        Starts the model. Used by spotpy
        """
        try:
            # Create a solver for differential equations
            solver = cmf.CVodeIntegrator(self.project, 1e-8)

            # New time series for model results
            dis_sim = cmf.timeseries(self.begin, cmf.day)
            # starts the solver and calculates the daily time steps
            end = self.end

            for t in solver.run(self.project.meteo_stations[0].T.begin,
                                end, cmf.day):

                # Fill the results (first year is included but not used to
                # calculate the NS)

                if t >= self.begin:
                    dis_sim.add(self.outlet.waterbalance(t))

            return dis_sim
        # Return an nan - array when a runtime error occurs
        except RuntimeError:
            dis_sim = np.array(self.dis_eval[
                            self.begin:self.end + datetime.timedelta(days=1)])\
                      * np.nan
            return dis_sim

    def simulation(self, vector):
        """
        SpotPy expects a method simulation. This methods calls set_parameters
        and run_models, so SpotPy is satisfied
        """
        paramdict = dict((pp.name, v) for pp, v in zip(self.params, vector))
        self.set_parameters(paramdict)
        discharge = self.run_model()
        discharge = np.array(discharge)
        # CMF outputs discharge in m³/day
        # Measured discharge is in m³/s but is internally converted to mm
        # Convert CMF output to mm as well
        area_catchment = 562.41
        discharge = (discharge * 1000) / (area_catchment * 1e6)
        return discharge

    def evaluation(self):
        """
        For Spotpy
        """
        # plus one day because as in lists the last entry is not included in
        # datetime objects
        dis_eval = self.dis_eval[self.begin:self.end +
                                 datetime.timedelta(days=1)]
        return np.array(dis_eval)

    def parameters(self):
        """
        For Spotpy
        """
        return spotpy.parameter.generate(self.params)

    @staticmethod
    def objectivefunction(simulation, evaluation):
        """
        For Spotpy
        """
        # Slice the arrays to only use the days of the calibration period
        # for objective function
        evaluation_calibration = evaluation[:1827]
        evaluation_validation = evaluation[1827:]
        simulation_calibration = simulation[:1827]
        simulation_validation = simulation[1827:]

        ns_calibration = spotpy.objectivefunctions.kge(
                                                        evaluation_calibration,
                                                        simulation_calibration)
        ns_validation = spotpy.objectivefunctions.kge(
                                                        evaluation_validation,
                                                        simulation_validation)

        return [ns_calibration, ns_validation]


if __name__ == '__main__':
    # 1979 is spin up
    # 1980 till 1984 is used for calibration
    # 1985 till 1989 is used for validation
    begin = 1980
    end = 1989

    prefix = "semi_dis_landuse"

    runs = 100000

    # File names of the forcing data
    subcatchment_names = ["grass_high", "wood_high", "rest_high",
                          "crops_high", "grass_low",
                          "wood_low", "rest_low", "crops_low"]

    # import algorithm
    from spotpy.algorithms import rope as sampler

    # Find out if the model should run parallel (for supercomputer)
    parallel = 'mpi' if 'OMPI_COMM_WORLD_SIZE' in os.environ else 'seq'

    # Create the model
    model = SemiDisLanduse(datetime.datetime(begin, 1, 1),
                           datetime.datetime(end, 12, 31),
                           subcatchment_names)
    sampler = sampler(model, parallel=parallel,
                      dbname="semi_dis_landuse_height_penman",
                      dbformat="csv", save_sim=True, save_threshold=[0, 0])
    sampler.sample(runs, subsets=30)
    #print(cmf.describe(model.project))
