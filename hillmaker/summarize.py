
import pandas as pd
import time

def summarize_bydatetime(bydt_df):
    """
    Create bydatetime table based on user inputs.

    This is the table from which summary statistics can be computed.

    Parameters
    ----------
    D : pandas DataFrame
       Stop data

    infield : string
       Name of column in D to use as arrival datetime

    outfield : string
       Name of column in D to use as departure datetime

    catfield : string
       Name of column in D to use as category field

    total_str : string
       Value to use for the totals

    bin_size_mins : int
       Bin size in minutes. Should divide evenly into 1440.

    Returns
    -------
    bydatetime: pandas DataFrame
       The computed bydatetime table as a DataFrame

    Examples
    --------



    TODO
    ----

    - add parameter and code to handle occ frac choice
    - generalize to handle choice of arr, dep, occ or some combo of

     Notes
    -----


    References
    ----------


    See Also
    --------
    """

    bydt_dfgrp = bydt_df.groupby(['category','day_of_week','bin_of_day'])

    occ_stats = bydt_dfgrp['occupancy'].apply(get_occstats)
    arr_stats = bydt_dfgrp['arrivals'].apply(get_occstats)
    dep_stats = bydt_dfgrp['departures'].apply(get_occstats)

    occ_stats_summary = occ_stats.unstack()
    arr_stats_summary = arr_stats.unstack()
    dep_stats_summary = dep_stats.unstack()

    print ('Done with summary stats: {}'.format(time.clock()))

    return (occ_stats_summary,arr_stats_summary,dep_stats_summary)


    # <markdowncell>

    # The real reason I exported them to csv was to make it easy to read these results back in for Part 3 of this series of tutorials. In Part 3, we'll create some plots using matplotlib based on these summary statistics.

def get_occstats(group, stub=''):
        return {stub+'count': group.count(), stub+'mean': group.mean(),
                stub+'min': group.min(),
                stub+'max': group.max(), 'stdev': group.std(),
                stub+'p50': group.quantile(0.5), stub+'p55': group.quantile(0.55),
                stub+'p60': group.quantile(0.6), stub+'p65': group.quantile(0.65),
                stub+'p70': group.quantile(0.7), stub+'p75': group.quantile(0.75),
                stub+'p80': group.quantile(0.8), stub+'p85': group.quantile(0.85),
                stub+'p90': group.quantile(0.9), stub+'p95': group.quantile(0.95),
                stub+'p975': group.quantile(0.975),
                stub+'p99': group.quantile(0.99)}

if __name__ == '__main__':

    scenario_name = 'sstest'
    file_bydt_pkl = 'data/bydatetime_' + scenario_name + '.pkl'


    bydt_df = pd.read_pickle(file_bydt_pkl)
    print ("Pickled bydt data file read: {}".format(time.clock()))

    occ_stats_summary,arr_stats_summary,dep_stats_summary = summarize_bydatetime(bydt_df)

    file_occ_csv = 'data/occ_stats_summary_' + scenario_name + '.csv'
    file_arr_csv = 'data/arr_stats_summary_' + scenario_name + '.csv'
    file_dep_csv = 'data/dep_stats_summary_' + scenario_name + '.csv'

    occ_stats_summary.to_csv(file_occ_csv)
    arr_stats_summary.to_csv(file_arr_csv)
    dep_stats_summary.to_csv(file_dep_csv)