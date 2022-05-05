"""
The :mod:`hillmaker.bydatetime` module includes functions for computing occupancy,
arrival, and departure statistics by time bin of day and date.
"""

# Copyright 2022 Mark Isken
#

import numpy as np
import pandas as pd
from pandas import DataFrame
from pandas import Series
from pandas import Timestamp
from datetime import datetime
from pandas.tseries.offsets import Minute

import hmlib


def make_bydatetime(stops_df, infield, outfield,
                    start_analysis, end_analysis, catfield=None,
                    bin_size_minutes=60,
                    cat_to_exclude=None,
                    totals=1,
                    occ_weight_field=None,
                    edge_bins=1,
                    verbose=0):
    """
    Create bydatetime table based on user inputs.

    This is the table from which summary statistics can be computed.

    Parameters
    ----------
    stops_df: DataFrame
        Stop data

    infield: string
        Name of column in stops_df to use as arrival datetime

    outfield: string
        Name of column in stops_df to use as departure datetime

    start_analysis: datetime
        Start date for the analysis

    end_analysis: datetime
        End date for the analysis

    catfield : string or List of strings, optional
        Column name(s) corresponding to the categories. If none is specified, then only overall occupancy is analyzed.

    bin_size_minutes: int, default 60
        Bin size in minutes. Should divide evenly into 1440.

    cat_to_exclude: list of strings, default None
        Categories to ignore

    edge_bins: int, default 1
        Occupancy contribution method for arrival and departure bins. 1=fractional, 2=whole bin

    totals: int, default 1
        0=no totals, 1=totals by datetime, 2=totals bydatetime as well as totals for each field in the
        catfields (only relevant for > 1 category field)

    occ_weight_field : string, optional (default=1.0)
        Column name corresponding to the weights to use for occupancy incrementing.

    verbose : int, default 0
        The verbosity level. The default, zero, means silent mode.

    Returns
    -------
    Dict of DataFrames
       Occupancy, arrivals, departures by category by datetime bin

    Examples
    --------
    bydt_dfs = make_bydatetime(stops_df, 'InTime', 'OutTime',
    ...                        datetime(2014, 3, 1), datetime(2014, 6, 30), 'PatientType', 60)

    bydt_dfs = make_bydatetime(stops_df, 'InTime', 'OutTime',
    ...           datetime(2014, 3, 1), datetime(2014, 6, 30), ['PatientType','Severity'], 60, totals=2)


    TODO
    ----


    Notes
    -----


    References
    ----------


    See Also
    --------
    """
    # Number of bins in analysis span
    num_bins = hmlib.bin_of_span(end_analysis, start_analysis, bin_size_minutes) + 1

    # Compute min and max of in and out times
    min_intime = stops_df[infield].min()
    max_intime = stops_df[infield].max()
    min_outtime = stops_df[outfield].min()
    max_outtime = stops_df[outfield].max()

    if verbose:
        print(f"min of intime: {min_intime}")
        print(f"max of intime: {max_intime}")
        print(f"min of outtime: {min_outtime}")
        print(f"max of outtime: {max_outtime}")

    # TODO - Add warnings here related to min and maxes out of whack with analysis range

    # Handle cases of no catfield, a single fieldname, or a list of fields
    # If no category, add a temporary dummy column populated with a totals str
    CONST_FAKE_CATFIELD_NAME = 'FakeCatForTotals'
    total_str = 'total'

    do_totals = True
    if catfield is not None:
        # If it's a string, it's a single cat field --> convert to list
        if isinstance(catfield, str):
            catfield = [catfield]
    else:
        totlist = [total_str] * len(stops_df)
        totseries = Series(totlist, dtype=str, name=CONST_FAKE_CATFIELD_NAME)
        totfield_df = DataFrame({CONST_FAKE_CATFIELD_NAME: totseries})
        stops_df = pd.concat([stops_df, totfield_df], axis=1)
        catfield = [CONST_FAKE_CATFIELD_NAME]
        do_totals = False   

    # Get the unique category values and exclude any specified to exclude
    categories = []
    if cat_to_exclude is not None:
        for i in range(len(catfield)):
            categories.append(tuple([c for c in stops_df[catfield[i]].unique() if c not in cat_to_exclude[i]]))
    else:
        for i in range(len(catfield)):
            categories.append(tuple([c for c in stops_df[catfield[i]].unique()]))

    for i in range(len(catfield)):
        stops_df = stops_df[stops_df[catfield[i]].isin(categories[i])]

    # TEMPORARY ASSUMPTION - only a single category field is allowed
    # Main loop over the categories. Filter stops_df by category and then do
    # numpy based occupancy computations.
    results = {}
    for cat in categories[0]:
        cat_df = stops_df[stops_df[catfield[0]] == cat]
        num_stop_recs = len(cat_df)

        # Create entry and exit bin arrays
        entry_bin = cat_df[infield].map(lambda x: hmlib.bin_of_span(x, start_analysis, bin_size_minutes)).to_numpy()
        exit_bin = cat_df[outfield].map(lambda x: hmlib.bin_of_span(x, start_analysis, bin_size_minutes)).to_numpy()

        # Compute inbin and outbin fractions - this part is SLOW
        entry_bin_frac = stops_df.apply(lambda x: in_bin_occ_frac(x[infield],
                                                                  bin_size_minutes, edge_bins=1), axis=1).to_numpy()
        exit_bin_frac = stops_df.apply(lambda x: out_bin_occ_frac(x[outfield],
                                                                  bin_size_minutes, edge_bins=1), axis=1).to_numpy()

        # Create list of occupancy incrementor arrays
        list_of_inc_arrays = [make_occ_incs(entry_bin[i], exit_bin[i],
                                            entry_bin_frac[i], exit_bin_frac[i]) for i in range(num_stop_recs)]

        # Create array of stop record types
        rec_type = cat_df.apply(lambda x:
                                hmlib.stoprec_analysis_rltnshp(x[infield], x[outfield],
                                                               start_analysis, end_analysis), axis=1).to_numpy()

        # Do the occupancy incrementing
        rec_counts = update_occ_incs(entry_bin, exit_bin, list_of_inc_arrays, rec_type, num_bins)
        print(rec_counts)

        occ = np.zeros(num_bins, dtype=np.float32)
        update_occ(occ, entry_bin, rec_type, list_of_inc_arrays)

        # Count arrivals and departures by bin
        arr = np.bincount(entry_bin, minlength=num_bins).astype(np.float32)
        dep = np.bincount(exit_bin, minlength=num_bins).astype(np.float32)

        # Combine arr, dep, occ (in that order) into matrix
        occ_arr_dep = np.column_stack((arr, dep, occ))
        
        # Store results
        results[cat] = occ_arr_dep

    # Do totals if there was at least one category field
    if do_totals:

        totals_key = 'datetime'
        total_occ_arr_dep = np.zeros((num_bins, 3), dtype=np.float32)
        for cat, oad_array in results.items():
            total_occ_arr_dep += oad_array
        
        results[totals_key] = total_occ_arr_dep

    return results


def arrays_to_dfs(results_arrays, start_analysis_dt, end_analysis_dt, bin_size_minutes, catfield):
    """
    Converts results dict from ndarrays to Dataframes

    results_arrays: dict of ndarrays
    """

    bydt_dfs = {}
    rng_bydt = Series(pd.date_range(start_analysis_dt, end_analysis_dt, freq=Minute(bin_size_minutes)))
    for cat, oad_array in results_arrays.items():
        # Create Dataframe from ndarray
        df = pd.DataFrame(oad_array, columns=['arrivals', 'departures', 'occupancy'])

        # Add datetime column and category column (still assuming just one category field)
        df['datetime'] = rng_bydt
        for c in catfield:
            df[c] = cat

        df['day_of_week'] = df['datetime'].map(lambda x: x.weekday())
        df['dow_name'] = df['datetime'].map(lambda x: x.day_name())
        df['bin_of_day'] = df['datetime'].map(lambda x: hmlib.bin_of_day(x, bin_size_minutes))
        df['bin_of_week'] = df['datetime'].map(lambda x: hmlib.bin_of_week(x, bin_size_minutes))

        # Create multi-index based on datetime and catfield
        midx_fields = catfield.copy()
        midx_fields.append('datetime')
        df.set_index(midx_fields, inplace=True, drop=True)
        df.sort_index(inplace=True)

        # Reorder the columns
        col_order = ['arrivals', 'departures', 'occupancy', 'day_of_week', 'dow_name', 
                         'bin_of_day', 'bin_of_week']
        df = df[col_order]

        bydt_dfs[cat] = df
    
    return bydt_dfs




def update_occ(occ, entry_bin, rec_type, list_of_inc_arrays):
    num_stop_recs = len(entry_bin)
    for i in range(num_stop_recs):
        if rec_type[i] in ['inner', 'left', 'right', 'outer']:
            pos = entry_bin[i]
            occ_inc = list_of_inc_arrays[i]
            try:
                occ[pos:pos + len(occ_inc)] += occ_inc
            except (IndexError, TypeError) as error:
                raise Exception(f'pos {pos} occ_inc {occ_inc}\n{error}')


def in_bin_occ_frac(in_ts, bin_size_minutes, edge_bins=1):
    """
    Computes fractional occupancy in inbin and outbin.

    Parameters
    ----------
    in_ts: Timestamp corresponding to entry time
    bin_size_minutes: bin size in minutes
    edge_bins: 1=fractional, 2=whole bin

    Returns
    -------
    inbin_occ_frac - Fraction of entry bin occupied - a real number in [0.0,1.0]

    """

    if edge_bins == 1:
        inbin_occ_frac = (in_ts.minute * 60.0 + in_ts.second) / (bin_size_minutes * 60.0)
    else:
        inbin_occ_frac = 1.0

    return inbin_occ_frac

def out_bin_occ_frac(out_ts, bin_size_minutes, edge_bins=1):
    """
    Computes fractional occupancy in inbin and outbin.

    Parameters
    ----------
    out_ts: Timestamp corresponding to exit time
    bin_size_minutes: bin size in minutes
    edge_bins: 1=fractional, 2=whole bin

    Returns
    -------
    outbin_occ_frac - Fraction of entry bin occupied - a real number in [0.0,1.0]

    """
    if edge_bins == 1:
        outbin_occ_frac = (bin_size_minutes * 60.0 - (out_ts.minute * 60.0 + out_ts.second)) / (bin_size_minutes * 60.0)
    else:
        outbin_occ_frac = 1.0

    return outbin_occ_frac


def make_occ_incs(in_bin, out_bin, in_frac, out_frac):

    n_bins = out_bin - in_bin + 1
    if n_bins > 2:
        ones = np.ones(n_bins - 2)
        occ_incs = np.concatenate((np.array([in_frac]), ones, np.array([out_frac])))
    elif n_bins == 2:
        occ_incs = np.concatenate((np.array([in_frac]), np.array([out_frac])))
    else:
        occ_incs = np.array([in_frac])
        
    return occ_incs

def update_occ_incs(in_bins, out_bins, list_of_inc_arrays, rec_types, num_bins):
    num_stop_recs = len(in_bins)
    rectype_counts = {}
    
    for i in range(num_stop_recs):
        if rec_types[i] == 'inner':
            rectype_counts['inner'] = rectype_counts.get('inner', 0) + 1 
        elif rec_types[i] == 'left':
             # arrival is outside analysis window (in_bin < 0)
            rectype_counts['left'] = rectype_counts.get('left', 0) + 1
            new_in_bin = 0
            bin_shift = -1 * in_bins[i]
            new_inc_array = list_of_inc_arrays[i][bin_shift:]
            # Update main arrays
            in_bins[i] = new_in_bin
            list_of_inc_arrays[i] = new_inc_array
        elif rec_types[i] == 'right':
            # departure is outside analysis window (out_bin >= num_bins)
            rectype_counts['right'] = rectype_counts.get('right', 0) + 1
            new_out_bin = num_bins - 1
            bin_shift = out_bins[i] - (num_bins - 1)
            # Keep all but the last bin_shift elements
            new_inc_array = list_of_inc_arrays[i][:-bin_shift]
            # Update main arrays
            out_bins[i] = new_out_bin
            list_of_inc_arrays[i] = new_inc_array
        elif rec_types[i] == 'outer':
            # This is combo of left and right
            rectype_counts['outer'] = rectype_counts.get('outer', 0) + 1
            new_in_bin = 0
            new_out_bin = num_bins - 1
            entry_bin_shift = -1 * in_bins[i]
            exit_bin_shift = out_bins[i] - (num_bins - 1)
            new_inc_array = list_of_inc_arrays[i][entry_bin_shift:-exit_bin_shift]
            # Update main arrays
            in_bins[i] = new_in_bin
            out_bins[i] = new_out_bin
            list_of_inc_arrays[i] = new_inc_array
        elif rec_types[i] == 'backwards':
            rectype_counts['backwards'] = rectype_counts.get('backwards', 0) + 1
        elif rec_types[i] == 'none':
            rectype_counts['none'] = rectype_counts.get('none', 0) + 1
        else:
            rectype_counts['unknown'] = rectype_counts.get('unknown', 0) + 1
        
    return rectype_counts


if __name__ == '__main__':
    # Required inputs
    scenario = 'sslittle_ex01'
    in_fld_name = 'InRoomTS'
    out_fld_name = 'OutRoomTS'
    #cat_fld_name = 'PatType'
    start_analysis = '1/1/1996'
    end_analysis = '1/3/1996 23:45'

    # Optional inputs
    verbose = 1
    output_path = './output/'

    # Create dfs
    file_stopdata = './data/ShortStay.csv'
    ss_df = pd.read_csv(file_stopdata, parse_dates=[in_fld_name, out_fld_name])

    dfs = make_bydatetime(ss_df, in_fld_name, out_fld_name, Timestamp(start_analysis), Timestamp(end_analysis))

    print(dfs.keys())

