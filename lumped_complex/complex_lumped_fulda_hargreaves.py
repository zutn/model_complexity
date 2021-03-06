#/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Jul 24 10:24 2017
@author(s): Florian U. Jehn
"""

import cmf
import spotpy
from spotpy.parameter import Uniform as param
import os
import datetime
import sys
import numpy as np
from dateutil.relativedelta import relativedelta


class ComplexLumped(object):
    """
    Class which contains the complete model, readeable for Spotpy
    """
    def __init__(self, begin, end):
        """Initializes the model and build the core setup"""
        # tr_soil_GW = Residence time of the water in the soil to the GW
        self.params = [param('tr_soil_gw', 0., 400.),
                       # tr_soil_fulda = residence time from soil to river
                       param("tr_soil_out", 0., 200.),

                       # tr_gw_upper_fulda = residence time from the upper
                       # groundwater to the river
                       param("tr_gw_out", 0., 650.),


                       # V0_soil = field capacity for the soil
                       param('V0_soil', 0., 300.),

                       # beta_soil_GW = Changes the flux curve of the soil
                       # to the groundwater
                       param('beta_soil_gw', 0.3, 6.0),

                       # beta_soil_out
                       param("beta_soil_out", 0.3, 8.0),


                       # ETV1 = the Volume that defines that the evaporation
                       # is lowered because of not enough water in the soil
                       param('ETV1', 0., 300.),
                       # fETV0 = factor the ET is multiplied by, when water is
                       #  low
                       param('fETV0', 0., 0.9),

                       # Rate of snow melt
                       param('meltrate', 0.01, 15.),
                       # Snow_melt_temp = Temperature at which the snow melts
                       # (needed because of averaged temp
                       param('snow_melt_temp', -3.0, 3.0),

                       # LAI = leaf area index
                       param('LAI', 1., 12),
                       # Canopy Closure
                       param("CanopyClosure", 0., 0.9),


                       ]
        self.begin = begin
        self.end = end

        # load the weather data and discharge data
        prec, temp, temp_min, temp_max, Q,  = self.loadPETQ()
        self.Q = Q

        # use only one core (faster when model is small
        cmf.set_parallel_threads(1)

        # Generate a cmf project with one cell for a lumped model
        self.project = cmf.project()
        p = self.project

        # Create a cell in the projectl_evapotranspiration
        c = p.NewCell(0, 0, 0, 1000)

        # Add snow storage
        c.add_storage("Snow", "S")
        cmf.Snowfall(c.snow, c)

        # Add the soil and groundwater layers
        soil = c.add_layer(2.0)
        gw_upper = c.add_layer(5.0)

        # Give the storages a initial volume
        soil.volume = 15
        gw_upper.volume = 80

        # Create a storage for Interception
        I = c.add_storage("Canopy", "C")

        # Install a calculation of the evaporation
        cmf.HargreaveET(soil, c.transpiration)

        # Create an outlet
        self.outlet = p.NewOutlet("outlet", 10, 0, 0)

        # Create the meteo stations
        self.make_stations(prec, temp, temp_min, temp_max)

        self.project = p


    def set_parameters(self,
                       tr_soil_gw,
                       tr_soil_out,
                       tr_gw_out,

                       V0_soil,

                       beta_soil_gw,
                       beta_soil_out,

                       ETV1,
                       fETV0,

                       meltrate,
                       snow_melt_temp,

                       LAI,
                       CanopyClosure,

                       ):
        """
        Creates all connections with the parameter values produced by the
        sampling algorithm.
        """
        # print("tr_soil_gw: {}; tr_soil_out: {}; tr_gw_out: {}; V0_soil: {}; "
        #       "beta_soil_gw: {}; beta_soil_out: {}; ETV1: {}; fETV0: {}; "
        #       "meltrate: {}; snow_melt_temp: {}; LAI: {}; CanopyClosure:"
        #       " {}\n".format(tr_soil_gw, tr_soil_out, tr_gw_out, V0_soil,
        #                  beta_soil_gw, beta_soil_out, ETV1, fETV0, meltrate,
        #                  snow_melt_temp, LAI, CanopyClosure))
        # Get all definition from the init method
        p = self.project
        c = p[0]
        outlet = self.outlet
        soil = c.layers[0]
        gw = c.layers[1]

        # Adjustment of the ET
        c.set_uptakestress(cmf.VolumeStress(ETV1, ETV1 * fETV0))

        # Flux from soil to outlet
        cmf.kinematic_wave(soil, outlet, tr_soil_out/V0_soil, V0=V0_soil, exponent=beta_soil_out)

        # Flux from soil to groundwater
        cmf.kinematic_wave(soil, gw, tr_soil_gw/V0_soil, V0=V0_soil, exponent=beta_soil_gw)

        # Flux from the  groundwater to the outlet (baseflow)
        cmf.kinematic_wave(gw, outlet, tr_gw_out)

        # Split the rainfall in interception and throughfall
        cmf.Rainfall(c.canopy, c, False, True)
        cmf.Rainfall(c.surfacewater, c, True, False)

        # Make an overflow for the interception storage
        cmf.RutterInterception(c.canopy, c.surfacewater, c)

        # Transpiration from the plants is added
        cmf.CanopyStorageEvaporation(c.canopy, c.evaporation, c)

        # Sets the paramaters for interception
        c.vegetation.LAI = LAI

        # Defines how much throughfall there is (in %)
        c.vegetation.CanopyClosure = CanopyClosure

        # # Set parameters of the snow calculations
        cmf.Weather.set_snow_threshold(snow_melt_temp)
        cmf.SimpleTindexSnowMelt(c.snow, soil, c, rate=meltrate)

    def loadPETQ(self):
        """
        Loads climata and discharge data from the corresponding files fnQ,
        fnT and fnP
        """
        # Fixed model starting point
        # Change this if you want a warm up period other than a year
        begin = self.begin - relativedelta(years=1)
        step = datetime.timedelta(days=1)
        # empty time series
        prec = cmf.timeseries(begin, step)
        prec.extend(float(Pstr.strip("\n")) for Pstr in open(fnP))

        discharge = cmf.timeseries(begin, step)
        discharge.extend(float(Qstr.strip("\n")) for Qstr in open(fnQ))
        # Convert m3/s to mm/day
        area_catchment = 562.41  # Change this when catchment changes!!!
        discharge *= 86400 * 1e3 / (area_catchment * 1e6)
        temp = cmf.timeseries(begin, step)
        temp_min = cmf.timeseries(begin, step)
        temp_max = cmf.timeseries(begin, step)

        # Go through all lines in the file
        for line in open(fnT):
            columns = line.strip("\n").split('\t')
            if len(columns) == 3:
                temp_max.add(float(columns[0]))
                temp_min.add(float(columns[1]))
                temp.add(float(columns[2]))

        return prec, temp, temp_min, temp_max, discharge

    def make_stations(self, prec, temp, temp_min, temp_max):
        """
        Creates the cmf weather stations
        """
        rainstation = self.project.rainfall_stations.add("Rainfall Station",
                                                         prec, (0, 0, 0))
        self.project.use_nearest_rainfall()

        # Temperature data
        meteo = self.project.meteo_stations.add_station('Grebenau avg', (0,
                                                                         0, 0))
        meteo.T = temp
        meteo.Tmin = temp_min
        meteo.Tmax = temp_max
        self.project.use_nearest_meteo()
        return rainstation

    def run_model(self):
        """
        Starts the model. Used by spotpy
        """

        try:
            # Create a solver for differential equations
            solver = cmf.CVodeIntegrator(self.project, 1e-8)

            # New time series for model results
            resQ = cmf.timeseries(self.begin, cmf.day)
            # starts the solver and calculates the daily time steps
            end = self.end
            for t in solver.run(self.project.meteo_stations[0].T.begin, end,
                                cmf.day):
                # Fill the results (first year is included but not used to
                # calculate the NS)
                if t >= self.begin:
                    resQ.add(self.outlet.waterbalance(t))
            return resQ
        # Return an nan - array when a runtime error occurs
        except RuntimeError:
            return np.array(self.Q[
                            self.begin:self.end + datetime.timedelta(
                                days=1)])*np.nan

    def simulation(self, vector):
        """
        SpotPy expects a method simulation. This methods calls set_parameters
        and run_models, so SpotPy is satisfied
        """
        paramdict = dict((pp.name, v) for pp, v in zip(self.params, vector))
        self.set_parameters(**paramdict)
        resQ = self.run_model()
        return np.array(resQ)

    def evaluation(self):
        """
        For Spotpy
        """
        return np.array(
            self.Q[self.begin:self.end + datetime.timedelta(days=1)])

    def parameters(self):
        """
        For Spotpy
        """
        return spotpy.parameter.generate(self.params)

    def objectivefunction(self, simulation, evaluation):
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
    # Whole modelling period
    # 1980 till 1986 is used for calibration
    # 1987 till 1992 is used for validation
    begin = 1980
    end = 1989

    # For validation data from Luterbacher is used
    prefix = "complex_lumped"

    # Number of runs
    runs = 100000

    # File names of the forcing data
    fnQ = "Q_Kammerzell_1979_1999.txt"
    fnT = "T_kammerzell_1979_1999_max_min_avg.txt"
    fnP = "P_Krigavg_kammerzell_1979_1999.txt"

    # import algorithm
    from spotpy.algorithms import rope as Sampler

    # Find out if the model should run parallel (for supercomputer)
    parallel = 'mpi' if 'OMPI_COMM_WORLD_SIZE' in os.environ else 'seq'

    # Create the model
    model = ComplexLumped(datetime.datetime(begin, 1, 1),
                               datetime.datetime(end, 12, 31))

    # If there is an command line argument, take its value for the amount of
    #  runs
    if len(sys.argv) > 1:
        runs = int(sys.argv[1])

    # run the model
    if runs:
        sampler = Sampler(model, parallel=parallel,
                          dbname="complex_lumped_hargreaves",
                          dbformat="csv", save_sim=True, save_threshold=[0.0,
                                                                        0.0])
        sampler.sample(runs, subsets=30)
