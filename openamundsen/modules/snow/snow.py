from numba import njit, prange
import numpy as np
from openamundsen import (
    constants as c,
)


def albedo(model, pos=None):
    """
    Update snow albedo using an exponential decay function.
    """
    s = model.state

    if pos is None:
        pos = model.grid.roi

    if model.config.snow.albedo.method == 'usaco':
        s.snow.albedo[pos] = _albedo_usaco(
            s.snow.albedo[pos],
            s.meteo.temp[pos],
            s.meteo.snowfall[pos] / model.timestep,
            model.config.snow.albedo.min,
            model.config.snow.albedo.max,
            model.config.snow.albedo.k_pos,
            model.config.snow.albedo.k_neg,
            model.config.snow.albedo.significant_snowfall / c.SECONDS_PER_HOUR,
            model.timestep,
        )
    elif model.config.snow.albedo.method == 'fsm':
        s.snow.albedo[pos] = _albedo_fsm(
            s.snow.albedo[pos],
            s.surface.temp[pos],
            s.meteo.snowfall[pos] / model.timestep,
            model.config.snow.albedo.min,
            model.config.snow.albedo.max,
            model.config.snow.albedo.melting_snow_decay_timescale,
            model.config.snow.albedo.cold_snow_decay_timescale,
            model.config.snow.albedo.refresh_snowfall,
            model.timestep,
        )
    else:
        raise NotImplementedError


def _albedo_usaco(
    albedo,
    temp,
    snowfall_rate,
    min_albedo,
    max_albedo,
    k_pos,
    k_neg,
    significant_snowfall,
    timestep,
):
    """
    Calculate snow albedo based on the aging curve approach by [1] and [2].

    Parameters
    ----------
    albedo : ndarray
        Current snow albedo.

    temp : ndarray
        Air temperature (K).

    snowfall_rate : ndarray
        Snowfall rate (kg m-2 s-1).

    min_albedo : float
        Minimum albedo that can be reached.

    max_albedo : float
        Maximum albedo for fresh snowfall.

    k_pos : float
        Decay parameter for positive air temperatures (d-1).

    k_neg : float
        Decay parameter for positive air temperatures (d-1).

    significant_snowfall : float
        Snowfall rate required for resetting albedo to the maximum value (kg
        m-2 s-1).

    timestep : float
        Model timestep (s).

    Returns
    -------
    albedo : ndarray
        Updated snow albedo.

    References
    ----------
    .. [1] Snow Hydrology: Summary Report of the Snow Investigations. Published
       by the North Pacific Division, Corps of Engineers, U.S. Army, Portland,
       Oregon, 1956.  437 pages, 70 pages of plates, maps and figs., 27 cm.
       https://doi.org/10.3189/S0022143000024503

    .. [2] Rohrer, Mario. (1992). Die Schneedecke im Schweizer Alpenraum und
       ihre Modellierung. Züricher Geographische Schriften. 49. 178.
    """
    k_scale_factor = timestep / (c.SECONDS_PER_HOUR * c.HOURS_PER_DAY)
    decay_factor = k_scale_factor * np.where(temp >= c.T0, k_pos, k_neg)
    albedo = min_albedo + (albedo - min_albedo) * np.exp(-decay_factor)
    albedo[snowfall_rate >= significant_snowfall] = max_albedo
    return albedo


def _albedo_fsm(
    albedo,
    surface_temp,
    snowfall_rate,
    min_albedo,
    max_albedo,
    melting_snow_decay_timescale,
    cold_snow_decay_timescale,
    refresh_snowfall,
    timestep,
):
    """
    Calculate snow albedo based on the approach by [1].

    Parameters
    ----------
    albedo : ndarray
        Current snow albedo.

    surface_temp : ndarray
        Surface temperature (K).

    snowfall_rate : ndarray
        Snowfall rate (kg m-2 s-1).

    min_albedo : float
        Minimum albedo that can be reached.

    max_albedo : float
        Maximum albedo for fresh snowfall.

    melting_snow_decay_timescale : float
        Melting snow albedo decay timescale (h).

    cold_snow_decay_timescale : float
        Cold snow albedo decay timescale (h).

    refresh_snowfall : float
        Snowfall for refreshing albedo (kg m-2).

    timestep : float
        Model timestep (s).

    Returns
    -------
    albedo : ndarray
        Updated snow albedo.

    References
    ----------
    .. [1] Essery, R. (2015). A factorial snowpack model (FSM 1.0).
       Geoscientific Model Development, 8(12), 3867–3876.
       https://doi.org/10.5194/gmd-8-3867-2015
    """
    albedo_decay_timescale = np.where(
        surface_temp >= c.T0,
        c.SECONDS_PER_HOUR * melting_snow_decay_timescale,
        c.SECONDS_PER_HOUR * cold_snow_decay_timescale,
    )
    reciprocal_albedo_timescale = 1 / albedo_decay_timescale + snowfall_rate / refresh_snowfall
    albedo_limit = (
        min_albedo / albedo_decay_timescale
        + snowfall_rate * max_albedo / refresh_snowfall
    ) / reciprocal_albedo_timescale
    decay_factor = reciprocal_albedo_timescale * timestep
    albedo = albedo_limit + (albedo - albedo_limit) * np.exp(-decay_factor)
    return albedo


def fresh_snow_density(temp):
    """
    Calculate fresh snow density based on the parameterization by [1] (eq. (4.22)).

    Parameters
    ----------
    temp : numeric
        Wet-bulb temperature (K) in the original formulation by [1]. Can be
        substituted by air temperature if not available.

    Returns
    -------
    rho : numeric
        Fresh snow density (kg m-3).

    References
    ----------
    .. [1] Anderson, E. A. (1976). A point energy and mass balance model of a
       snow cover (NOAA Technical Report NWS 19, pp. 1–172). NOAA.
       https://repository.library.noaa.gov/view/noaa/6392
    """
    min_temp = c.T0 - 15.
    temp = np.array(temp).clip(min_temp)  # the parameterization is only valid for temperatures >= -15 °C
    rho = 50 + 1.7 * (temp - min_temp)**1.5
    rho[np.isnan(rho)] = 100.  # if temperature is not available, set density to 100 kg m-3
    return rho


def compaction(model):
    snow = model.state.snow

    if model.config.snow.compaction.method == 'anderson':
        _compaction_anderson(
            model.grid.roi_idxs,
            model.timestep,
            snow.num_layers,
            snow.thickness,
            snow.ice_content,
            snow.liquid_water_content,
            snow.density,
            model.state.meteo.temp,
        )
    elif model.config.snow.compaction.method == 'fsm':
        timescale = c.SECONDS_PER_HOUR * model.config.snow.compaction.timescale  # snow compaction timescale (s)
        _compaction_fsm(
            model.grid.roi_idxs,
            model.timestep,
            timescale,
            model.config.snow.compaction.max_cold_density,
            model.config.snow.compaction.max_melting_density,
            snow.num_layers,
            snow.temp,
            snow.thickness,
            snow.ice_content,
            snow.liquid_water_content,
            snow.density,
        )
    else:
        raise NotImplementedError


@njit(cache=True, parallel=True)
def _compaction_anderson(
    roi_idxs,
    timestep,
    num_layers,
    thickness,
    ice_content,
    liquid_water_content,
    density,
    air_temp,
):
    """
    Calculate snow compaction following [1].
    Parameter names (c1...c7) are changed compared to the original
    formulation, follwing [2].

    Parameters
    ----------
    roi_idxs : ndarray(int, ndim=2)
        (N, 2)-array specifying the (row, col) indices within the data arrays
        that should be considered.

    timestep : float
        Model timestep (s).

    num_layers : ndarray(float, ndim=2)
        Number of snow layers.

    thickness : ndarray(float, ndim=3)
        Snow thickness (m).

    ice_content : ndarray(float, ndim=3)
        Ice content of snow (kg m-2).

    liquid_water_content : ndarray(float, ndim=3)
        Liquid water content of snow (kg m-2).

    density : ndarray(float, ndim=3)
        Snow density (kg m-3).

    air_temp : ndarray(float, ndim=2)
        Air temperature (K).

    References
    ----------
    .. [1] Anderson, E. A. (1976). A point energy and mass balance model of a
       snow cover (NOAA Technical Report NWS 19, pp. 1–172). NOAA.
       https://repository.library.noaa.gov/view/noaa/6392

    .. [2] Koivusalo, H., Heikinheimo, M., & Karvonen, T. (2001). Test of a
       simple two-layer parameterisation to simulate the energy balance and
       temperature of a snow pack. Theoretical and Applied Climatology, 70(1–4),
       65–79. https://doi.org/10.1007/s007040170006
    """
    timestep_h = timestep / c.SECONDS_PER_HOUR  # model timestep (h)

    c1 = 0.001  # m2 kg-1 h-1
    c2 = 0.08  # K-1
    c3 = 0.021  # m3 kg-1
    c5 = 0.04  # K-1
    c7 = 0.046  # m3 kg-1
    rho_d = 150.  # kg m-3

    num_pixels = len(roi_idxs)
    for idx_num in prange(num_pixels):
        i, j = roi_idxs[idx_num]
        load = 0.  # snow load (mass of layers above + 50% of the current layer) (kg m-2)

        for k in range(num_layers[i, j]):
            if thickness[k, i, j] > 0:  # TODO is this necessary?
                load += (ice_content[k, i, j] + liquid_water_content[k, i, j]) / 2.

                # TODO rather update density in update_layers()?
                density[k, i, j] = (ice_content[k, i, j] + liquid_water_content[k, i, j]) / thickness[k, i, j]

                if density[k, i, j] > rho_d:
                    c6 = np.exp(-c7 * (density[k, i, j] - rho_d))
                else:
                    c6 = 1.

                # Parameter c4 has an enhancement factor of 2 for wet snow
                if liquid_water_content[k, i, j] > 0:
                    c4 = 0.02  # h-1
                else:
                    c4 = 0.01  # h-1

                # Densification due to snow load (eq. (3.29) in [1], eq. (12) in [2])
                dens_compact = c1 * load * np.exp(-c2 * (c.T0 - air_temp[i, j]) - c3 * density[k, i, j])

                # Densification due to destructive metamorphism (eq. (3.31) in [1], eq. (13) in [2])
                dens_metamorph = c4 * np.exp(-c5 * (c.T0 - air_temp[i, j])) * c6

                densification_rate = density[k, i, j] * (dens_compact + dens_metamorph)
                if np.isnan(densification_rate):
                    densification_rate = 0.

                density[k, i, j] += densification_rate * timestep_h
                thickness[k, i, j] = (ice_content[k, i, j] + liquid_water_content[k, i, j]) / density[k, i, j]

                # Update snow load for the next layer
                load += (ice_content[k, i, j] + liquid_water_content[k, i, j])


@njit(cache=True, parallel=True)
def _compaction_fsm(
    roi_idxs,
    timestep,
    timescale,
    max_cold_density,
    max_melting_density,
    num_layers,
    temp,
    thickness,
    ice_content,
    liquid_water_content,
    density,
):
    """
    Calculate snow compaction following [1].

    Parameters
    ----------
    roi_idxs : ndarray(int, ndim=2)
        (N, 2)-array specifying the (row, col) indices within the data arrays
        that should be considered.

    timestep : float
        Model timestep (s).

    timescale : float
        Snow compaction timescale (s).

    max_cold_density : float
        Maximum density for cold (T < 0 °C) snow (kg m-2).

    max_melting_density : float
        Maximum density for melting snow (kg m-2).

    num_layers : ndarray(float, ndim=2)
        Number of snow layers.

    temp : ndarray(float, ndim=3)
        Snow temperature (K).

    thickness : ndarray(float, ndim=3)
        Snow thickness (m).

    ice_content : ndarray(float, ndim=3)
        Ice content of snow (kg m-2).

    liquid_water_content : ndarray(float, ndim=3)
        Liquid water content of snow (kg m-2).

    density : ndarray(float, ndim=3)
        Snow density (kg m-3).

    References
    ----------
    .. [1] Essery, R. (2015). A factorial snowpack model (FSM 1.0).
       Geoscientific Model Development, 8(12), 3867–3876.
       https://doi.org/10.5194/gmd-8-3867-2015
    """
    num_pixels = len(roi_idxs)
    for idx_num in prange(num_pixels):
        i, j = roi_idxs[idx_num]

        for k in range(num_layers[i, j]):
            if thickness[k, i, j] > 0:  # TODO is this necessary?
                # TODO rather update density in update_layers()?
                density[k, i, j] = (ice_content[k, i, j] + liquid_water_content[k, i, j]) / thickness[k, i, j]

                if temp[k, i, j] < c.T0:
                    max_density = max_cold_density
                else:
                    max_density = max_melting_density

                if density[k, i, j] < max_density:
                    # Where the maximum density is already reached, do not increase it anymore
                    # but to avoid jumps do not actually clip the values (because snow might
                    # switch between "cold" and "melting" from one timestep to another)
                    density[k, i, j] = (
                        max_density
                        + (density[k, i, j] - max_density)
                        * np.exp(-timestep / timescale)
                    )

                    thickness[k, i, j] = (ice_content[k, i, j] + liquid_water_content[k, i, j]) / density[k, i, j]


def snow_properties(model):
    """
    Update snow properties (depth, SWE, snow cover fraction, heat capacity).

    Parameters
    ----------
    model : OpenAmundsen
        openAMUNDSEN model instance.

    References
    ----------
    .. [1] Essery, R. (2015). A factorial snowpack model (FSM 1.0).
       Geoscientific Model Development, 8(12), 3867–3876.
       https://doi.org/10.5194/gmd-8-3867-2015
    """
    snow = model.state.snow

    snow.depth[:] = snow.thickness.sum(axis=0)
    snow.swe[:] = (snow.ice_content + snow.liquid_water_content).sum(axis=0)

    # Snow cover fraction (eq. (13))
    snow.area_fraction[:] = np.tanh(snow.depth / model.config.snow.snow_cover_fraction_depth_scale)

    # Areal heat capacity of snow (eq. (9))
    snow.heat_cap[:] = (
        snow.ice_content * c.SPEC_HEAT_CAP_ICE
        + snow.liquid_water_content * c.SPEC_HEAT_CAP_WATER
    )


def max_liquid_water_content(model):
    """
    Calculate the maximum liquid water content of snow.

    The following options for calculating the maximum liquid water content are
    supported:
        - 'pore_volume_fraction': maximum LWC is set to a fraction of the snow
          pore volume following [1].
        - 'mass_fraction': maximum LWC is set to a fraction of the snow
          ice mass.

    Parameters
    ----------
    model : OpenAmundsen
        openAMUNDSEN model instance.

    Returns
    -------
    max_lwc : ndarray(float, ndim=3)
        Maximum liquid water content (kg m-2).

    References
    ----------
    .. [1] Essery, R. (2015). A factorial snowpack model (FSM 1.0).
       Geoscientific Model Development, 8(12), 3867–3876.
       https://doi.org/10.5194/gmd-8-3867-2015
    """
    s = model.state
    method = model.config.snow.liquid_water_content.method

    if method == 'pore_volume_fraction':
        pos = s.snow.thickness > 0.
        porosity = np.zeros(s.snow.ice_content.shape)

        porosity[pos] = 1 - s.snow.ice_content[pos] / (c.ICE_DENSITY * s.snow.thickness[pos])  # eq. (27)

        max_lwc = (  # eq. (28)
            c.WATER_DENSITY
            * s.snow.thickness
            * porosity
            * model.config.snow.liquid_water_content.max
        )
    elif method == 'mass_fraction':
        max_lwc = model.config.snow.liquid_water_content.max * s.snow.ice_content

    return max_lwc
