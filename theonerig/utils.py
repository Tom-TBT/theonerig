# AUTOGENERATED! DO NOT EDIT! File to edit: 01_utils.ipynb (unless otherwise specified).

__all__ = ['extend_sync_timepoints', 'align_sync_timepoints', 'resample_to_timepoints', 'link_sync_timepoints',
           'flip_stimulus', 'flip_gratings', 'stim_to_dataChunk', 'phy_results_dict', 'spike_to_dataChunk',
           'get_calcium_stack_lenghts', 'twoP_dataChunks', 'img_2d_fit', 'fill_nan', 'stim_inten_norm',
           'group_direction_response', 'group_chirp_bumps', 'get_repeat_corrected', 'removeSlowDrift',
           'time_shift_test_corr', 'cross_corr_with_lag', 'get_inception_generator', 'group_omitted_epochs',
           'get_shank_channels', 'format_pval', 'stim_recap_df']

# Cell
import numpy as np
import pandas as pd
import os
import glob
import re
from typing import Dict, Tuple, Sequence, Union, Callable
import scipy.interpolate as interpolate
from scipy.ndimage import convolve1d
from scipy.signal import savgol_filter
import scipy.stats
from scipy.ndimage import gaussian_filter
import matplotlib.pyplot as plt
import math
from cmath import *
from PIL import Image

from .core import *

# Cell
def extend_sync_timepoints(timepoints:np.ndarray, signals:np.ndarray,
                           up_bound, low_bound=0) -> Tuple[DataChunk, DataChunk]:
    """
    Extend arrays of timepoints and signals (with identical shape) from the low_bound up to the up_bound.
    For example, the first timepoint could be 2000, and with a low_bound of 0, it would add the
    timepoints 0, 500, 1000, 1500 if the timepoint distance is of 500 (obtained by averaging the timepoints
    distances).

    params:
        - timepoints: Timepoints to extend
        - signals: Signals to extend
        - up_bound: Up bound to which to extend both timepoints and signals
        - low_bound: Low bound to which to extend both timepoints and signals

    returns:
        - timepoint: Extended timepoints
        - signals: The datachunk array is not modified, but the idx attribute is increased by the number
        of frames added with the low_bound.
    """
    assert len(timepoints) == len(signals)
    timepoints = np.array(timepoints)
    signals = np.array(signals)
    spb = np.mean(timepoints[1:]-timepoints[:-1]) #spf: sample_per_bin

    #Left and right side are just prolongation of the sample_times up
    # from (0-sample_per_fr) to (len+sample_per_fr) so it covers all timepoints
    left_side  = np.arange(timepoints[0]-spb , low_bound - spb, -spb)[::-1].astype(int)
    right_side = np.arange(timepoints[-1]+spb,  up_bound + spb,  spb).astype(int)

    new_timepoints = np.concatenate((left_side,
                                     timepoints,
                                     right_side))

    timepoint_chunk = DataChunk(data=new_timepoints, idx=0, group="sync")
    signal_chunk    = DataChunk(data=signals, idx=len(left_side), group="sync")
    return (timepoint_chunk, signal_chunk)

# Cell
def align_sync_timepoints(timepoints:DataChunk, signals:DataChunk,
                          ref_timepoints:DataChunk, ref_signals:DataChunk) -> Tuple[DataChunk, DataChunk, DataChunk]:
    """
    Align the signals of a timepoints timeserie to a reference ref_timepoints with the corresponding
    ref_signals. ref_timepoints is extended to match ref_timepoints lenght.

    params:
        - timepoints: timepoints to align
        - signals: signals to align
        - ref_timepoints: reference timepoints
        - ref_signals: reference signals

    return:
        - Aligned timepoints (DataChunk)
        - Aligned signals (DataChunk)
    """
    shift_left = ((np.where(ref_signals)[0][0] + ref_signals.idx)
                  - (np.where(signals)[0][0] + signals.idx))
    shift_right   = len(ref_timepoints) - (len(timepoints) + shift_left)

    spb     = np.mean(timepoints[1:]-timepoints[:-1]) #spf: sample_per_bin
    spb_ref = np.mean(ref_timepoints[1:]-ref_timepoints[:-1]) #spf: sample_per_bin

    left_timepoints      = np.zeros(0)
    left_timepoints_ref  = np.zeros(0)
    right_timepoints     = np.zeros(0)
    right_timepoints_ref = np.zeros(0)

    if shift_left > 0: #the ref started before, need to extend the other
        init  = timepoints[0]-spb
        left_timepoints = np.arange(init ,
                                    init-(spb*shift_left+1),
                                    -spb)[:shift_left][::-1].astype(int)
    else:
        shift_left = abs(shift_left)
        init  = ref_timepoints[0]-spb_ref
        left_timepoints_ref = np.arange(init ,
                                        init-(spb_ref*shift_left+1),
                                        -spb_ref)[:shift_left][::-1].astype(int)
        #We also need to shift the index of the ref signals since we increased the size of the ref_timepoints
        ref_signals.idx = ref_signals.idx + len(left_timepoints_ref)

    if shift_right > 0: #the ref ended after, need to extend the other
        init  = timepoints[-1]+spb
        right_timepoints = np.arange(init ,
                                    init+(spb*shift_right+1),
                                    spb)[:shift_right].astype(int)
    else:
        shift_right = abs(shift_right)
        init  = ref_timepoints[-1]+spb_ref
        right_timepoints_ref = np.arange(init ,
                                    init+(spb_ref*shift_right+1),
                                    spb_ref)[:shift_right].astype(int)

    timepoint    = DataChunk(data=np.concatenate((left_timepoints,
                                     timepoints,
                                     right_timepoints)), idx=0, group="sync")

    timepoint_ref = DataChunk(data=np.concatenate((left_timepoints_ref,
                                     ref_timepoints,
                                     right_timepoints_ref)), idx=0, group="sync")

    return (timepoint, timepoint_ref, ref_signals)

# Cell
def resample_to_timepoints(timepoints:np.ndarray, data:np.ndarray,
                             ref_timepoints:DataChunk, group="data") -> DataChunk:
    """
    Resample the data at timepoints to new timepoints given by ref_timepoints.
    Return a DataChunk of the resampled data belonging to a specified group.

    params:
        - timepoints: Original timepoints of the data
        - data: Data to resample of shape (t, ...)
        - ref_timepoints: Target timepoints for the resampling
        - group: Group assigned to the returned DataChunk

    return:
        - Resampled datachunk with appropriate idx.
    """

    assert len(timepoints) == len(data)
    timepoints = np.array(timepoints)
    data = np.array(data)

    start_idx = np.argmax(ref_timepoints >= timepoints[0])
    stop_idx  = np.argmax(ref_timepoints >= timepoints[-1])
    if stop_idx == 0:
        stop_idx = len(ref_timepoints)

    if len(ref_timepoints[start_idx:stop_idx]) < len(timepoints): #Downsampling
        distance = (np.argmax(timepoints>ref_timepoints[start_idx+1])
                - np.argmax(timepoints>ref_timepoints[start_idx]))

        kernel = np.ones(distance)/distance
        data = convolve1d(data, kernel, axis=0) #Smooting to avoid weird sampling

    new_data = interpolate.interp1d(timepoints, data, axis=0)(ref_timepoints[start_idx:stop_idx])

    idx = ref_timepoints.idx + start_idx
    return DataChunk(data=new_data, idx = idx, group=group)

# Cell
def link_sync_timepoints(frame_tp_1, frame_sig_1, frame_tp_2, frame_sig_2):
    """
    Creates timepoints between two timepoints array sampled at the same rate.
    This is usefull for the LED dome which cannot generate frames in between stimuli (due to ROM update)

    params:
        - frame_tp_1: Timepoints of the first part
        - frame_sig_1: Signals of the first part
        - frame_tp_2: Timepoints of the second part
        - frame_sig_2: Signals of the second part
    return:
        - (concatenated_frame_timepoints, concatenated_frame_signals)
    """
    assert abs(np.diff(frame_tp_1).mean() - np.diff(frame_tp_2).mean())<10, "The frame rates are different"
    assert len(frame_tp_1)==len(frame_sig_1), "The lenght of the first signals and timepoints do not match"
    assert len(frame_tp_2)==len(frame_sig_2), "The lenght of the second signals and timepoints do not match"

    n_tp = np.diff(frame_tp_1).mean()
    n_new_frames = int(round((frame_tp_2[0] - frame_tp_1[-1])/n_tp) - 1)
    new_frames = np.linspace(int(frame_tp_1[-1]+n_tp), frame_tp_2[0], n_new_frames, endpoint=False).astype(int)

    concat_frame_tp  = np.concatenate((frame_tp_1, new_frames, frame_tp_2))
    concat_frame_sig = np.concatenate((frame_sig_1, [0]*n_new_frames, frame_sig_2))

    return concat_frame_tp, concat_frame_sig

# Cell
def flip_stimulus(stim_inten, ud_inv, lr_inv):
    """
    Flip QDSpy stimuli arrays to match the up/down left/right orientation of the stimulus displayed to
    the mouse.

    params:
        - stim_inten: Stimulus matrix to flip of shape (t, color, y, x)
        - ud_inv: Up down inversion boolean (1 to make the flip, 0 for no operation)
        - lr_inv: Up down inversion boolean (1 to make the flip, 0 for no operation)

    return:
        - Flipped stimulus array
    """
    if lr_inv:
        stim_inten = np.flip(stim_inten, axis=3) # Axis 0:t 1:color 2:y 3:x
    if not ud_inv:
        #Numpy and QDSpy orientation are different.
        #This way reorientate the stimulus approriatly for display with matplotlib and potential
        #eye tracking corrections
        stim_inten = np.flip(stim_inten, axis=2)
    return stim_inten

def flip_gratings(stim_shader, ud_inv, lr_inv):
    """
    Flip gratings to match the up/down left/right orientation of the stimulus displayed to
    the mouse. A grating is encoded by an array of shape (t, 3(size, angle, speed)).
    Therefore the angles of the grating are modified to encode the "flipped" grating.

    params:
        - stim_shader: Grating matrix to flip of shape (t, 3(size, angle(degree), speed))
        - ud_inv: Up down inversion boolean (1 to make the flip, 0 for no operation)
        - lr_inv: Up down inversion boolean (1 to make the flip, 0 for no operation)

    return:
        - Flipped grating array
    """
    mask_epochs = ~np.all(stim_shader==0,axis=1)
    if lr_inv:
        stim_shader[mask_epochs,1] = (360 + (180 - stim_shader[mask_epochs,1])) % 360
    if ud_inv:
        stim_shader[mask_epochs,1] = (360 - stim_shader[mask_epochs,1]) % 360
    return stim_shader

def stim_to_dataChunk(stim_inten, stim_start_idx, reference:DataChunk) -> DataChunk:
    """
    Factory function for DataChunk of a stimulus, that squeeze the stim_inten matrix.

    params:
        - stim_inten: Stimulus matrix of shape (t, ...)
        - stim_start_idx: Starting frame index of the stimulus
        - reference: DataChunk signal reference used to determine the starting index of the stimulus

    return:
        - Datachunk of the stimulus
    """
    return DataChunk(data=np.squeeze(stim_inten), idx = (stim_start_idx + reference.idx), group="stim")

# Cell
def phy_results_dict(phy_dir):
    """
    Open the result arrays of spike sorting after manual merging with phy.

    params:
        - phy_dir: path to the phy results

    return:
        - Dictionnary of the phy arrays (amplitudes, channel_map, channel_positions, spike_clusters,
        spike_templates, spike_times, templates)
    """
    res_dict = {}
    res_dict["amplitudes"] = np.load(phy_dir+"/amplitudes.npy")
    res_dict["channel_map"] = np.load(phy_dir+"/channel_map.npy")
    res_dict["channel_positions"] = np.load(phy_dir+"/channel_positions.npy")
    res_dict["spike_clusters"] = np.load(phy_dir+"/spike_clusters.npy")
    res_dict["spike_templates"] = np.load(phy_dir+"/spike_templates.npy")
    res_dict["spike_times"] = np.load(phy_dir+"/spike_times.npy")
    res_dict["templates"] = np.load(phy_dir+"/templates.npy")
    if os.path.isfile(phy_dir+"/channel_shanks.npy"): #Newer version of phy/spyking-circus
        res_dict["channel_shanks"] = np.load(phy_dir+"/channel_shanks.npy")
        res_dict["template_ind"]   = np.load(phy_dir+"/template_ind.npy")

    return res_dict

def spike_to_dataChunk(spike_timepoints, ref_timepoints:DataChunk) -> DataChunk:
    """
    Factory function of a DataChunk for spiking count of cells from spike timepoints.

    params:
        - spike_timepoints: Dictionnary of the cells spike timepoints (list)
        - ref_timepoints: Reference DataChunk to align the newly created spike count Datachunk

    return:
        - Spike count datachunk of shape (t, n_cell)
    """
    type_cast = type(list(spike_timepoints.keys())[0])
    cell_keys = sorted(map(int,
                                    spike_timepoints.keys()))
    cell_map = dict([ (cell_key, i) for i, cell_key in enumerate(cell_keys) ])
    spike_bins = np.zeros((ref_timepoints.shape[0], len(cell_keys)))
    bins = np.concatenate((ref_timepoints[:], [(ref_timepoints[-1]*2)-ref_timepoints[-2]]))

    for i, cell in enumerate(cell_keys):
        spike_bins[:, i] = np.histogram(spike_timepoints[type_cast(cell)], bins)[0]

    datachunk = DataChunk(data=spike_bins, idx = ref_timepoints.idx, group="cell")
    datachunk.attrs["cell_map"] = cell_map
    return datachunk

# Cell
def get_calcium_stack_lenghts(folder):
    """
    Function to extract calcium stack lenghts from imageJ macro files associated to the stacks.

    params:
        - folder: path of the folder containing the IJ macros files

    return:
        - list of stack lenghts
    """
    record_lenghts = []
    pattern_nFrame = r".*number=(\d*) .*"
    for fn in glob.glob(folder+"/*.txt"):
        with open(fn) as f:
            line = f.readline()
            record_lenghts.append(int(re.findall(pattern_nFrame, line)[0]))
    return record_lenghts

def twoP_dataChunks(ref_timepoints:DataChunk, frame_timepoints, len_epochs, *args):
    """
    Factory function for two photon data.

    params:
        - ref_timepoints: Reference timepoints to create the DataChunk
        - frame_timepoints: List of frame timepoints for each sequence of two photon frame recorded.
        - len_epochs: Lenght of the recorded epochs (<= than the corresponding frame_timepoints). Int or list
        - args: matrices of all frames detected by CaImAn. (give as many as you want to synchronise)

    return:
        - tuple containing the synchronised matrices in the order it was given
    """
    assert len(args)>=1, "no matrix to be synchronised was given"
    res_l = [[] for i in range(len(args))]
    cursor = 0
    if isinstance(len_epochs, int):
        len_epochs = [len_epochs]
    # For every recording block (defined by len_epochs),
    for i, len_epoch in enumerate(len_epochs):
        start_idx = np.argmax(ref_timepoints>frame_timepoints[i][0])
        stop_idx  = np.argmax(ref_timepoints>frame_timepoints[i][len_epoch-1])
        for k, matrix in enumerate(args):
            sub_mat = matrix.T[cursor:cursor+len_epoch]

            f = interpolate.interp1d(range(len_epoch), sub_mat, axis=0)
            res_l[k].append(DataChunk(data=f(np.linspace(0,len_epoch-1,stop_idx-start_idx)),
                                           idx=start_idx,
                                           group="cell"))
        cursor += len_epoch

    return tuple(res_l)

# Cell
def img_2d_fit(shape, param_d, f):
    """
    Helper function to generate the 2D image of a fit.

    params:
        - shape: Shape of the image in (y, x).
        - param_d: Fit dictionnary.
        - f: Function used of the fit.
    """
    y_, x_ = shape
    xy = np.meshgrid(range(x_), range(y_))
    return f(xy, **param_d).reshape(y_, x_)

# Cell
def fill_nan(A):
    """
    Fill nan values with interpolation. Credits to BRYAN WOODS@StackOverflow
    """
    inds = np.arange(A.shape[0])
    good = np.where(np.isfinite(A))
    f = interpolate.interp1d(inds[good], A[good],bounds_error=False)
    B = np.where(np.isfinite(A),A,f(inds))
    return B

# Cell
def stim_inten_norm(stim_inten):
    """
    Normalize a stimulus with intensity in the 8bit range (0-255) to -1 to 1 range.
    """
    stim_inten = stim_inten.astype(float)
    stim_inten -= np.min(stim_inten)
    stim_inten -= np.max(stim_inten)/2
    stim_inten /= np.max(np.abs(stim_inten))
    return np.round(stim_inten, 5)

# Cell
def group_direction_response(stim_prop, spike_counts, n_repeat, n_cond=32):
    """
    Group the cells responses from shuffled grating stimulus repetitions. Retrieves a dictionnary
    with a key for each condition.

    params:
        - stim_prop: Grating array of shape (t, 3(size, angle, speed))
        - spike_counts: Spike counts response of the cells of shape (t, n_cell)
        - n_repeat: Number of repeat of each condition
        - n_cond: Total number of condition (speed/size condition * n_angle)

    return:
        - dictionnary of the spike counts for each condition (speed/size), with shape (n_angle, n_repeat, len, n_cell)
    """

    n_cell = spike_counts.shape[-1]
    condition_repeat = stim_prop.reshape(n_repeat*n_cond,-1,3)[:,10,:] #Take the condition for each repeat
    # We take it at the 10th frame in case of frame replacement during synchronisation
    #(the 10th should be unchanged)

    #Reshape the spike response to (n_cond, len, n_cell)
    spike_resh       = spike_counts.reshape(n_repeat*n_cond,-1,n_cell)

    angles = np.unique(condition_repeat[:,1])

    data_dict = {}
    for cond in np.unique(condition_repeat, axis=0):
        spat_freq, angle, speed = tuple(cond)
        idx_cond = np.argwhere(np.all(condition_repeat==cond, axis=1))[:,0]

        cond_key = str(spat_freq)+"@"+str(round(speed,2))
        if cond_key not in data_dict.keys():
            data_dict[cond_key] = np.empty((len(angles), len(idx_cond), *spike_resh[0].shape))

        idx_angle = np.where(angle==angles)[0][0]
        data_dict[cond_key][idx_angle] = np.array([spike_resh[idx] for idx in idx_cond])
    return data_dict

# Cell
def group_chirp_bumps(stim_inten, spike_counts, n_repeat):
    """
    Find the cells response to the OFF-ON-OFF initial parts of the chirps.

    params:
        - stim_inten: Stimulus intensity array
        - spike_counts: Spike counts array of shape (t, n_cell)
        - n_repeat: Number of repetitions of the chirp stimulus

    return:
        - Dictionnary of cells response to the different ON or OFF stimuli
    """

    repeat = stim_inten.reshape(n_repeat,-1)[0]
    spike_counts = spike_counts.reshape(n_repeat,-1,spike_counts.shape[-1])
    epoch_l = [0]
    end_l = [len(repeat)]
    i = 1
    curr = repeat[0]

    while True:
        while repeat[i]==curr:
            i+=1
        epoch_l.append(i)
        curr = repeat[i]
        if curr==repeat[i+1]:
            continue
        else:
            break

    i = len(repeat)-2
    curr = repeat[-1]

    while True:
        while repeat[i]==curr:
            i-=1
        end_l.insert(0,i)
        curr = repeat[i]
        if curr==repeat[i-1]:
            continue
        else:
            break
    slices = [slice(epoch_l[i-1],epoch_l[i]) for i in range(1,len(epoch_l))]
    slices.extend([slice(end_l[i-1],end_l[i]) for i in range(1,len(end_l))])

    res_d = {}
    for slc in slices:
        key = str(stim_inten[slc.start])+"@"+str(slc.start)
        res_d[key] = spike_counts[:,slc]

    return res_d

# Cell
def get_repeat_corrected(stim_inten, spike_counts, n_repeats=10):
    """
    Apply shifts (detected during synchro) to the chirp repetition.

    params:
        - stim_inten: Stimulus DataChunk (containing the shifts and frame replacements info)
        - spike_counts: Spike count matrix of shape (t, n_cell)
        - n_repeats: Number of repeats of the chirp

    return:
        - aligned cells response to stimulus, of shape (n_repeat, t, n_cell)
        - Number of duplicated frame per repetition.
    """
    def count_repl_in_range(fr_replaced, _range):
        return sum([repl[0] in _range for repl in fr_replaced])

    signal_shifts     = stim_inten.attrs["signal_shifts"]
    frame_replacement = stim_inten.attrs["frame_replacement"]

    spike_count_corr = spike_counts.copy()
    shift_cursor = 0
    prev_del = np.zeros((1, spike_counts.shape[1]))
    for shift, direction in signal_shifts:
        if direction=="ins":
            spike_count_corr[shift+1:] = spike_count_corr[shift:-1]
            prev_del = spike_count_corr[-1:]
        else:
            spike_count_corr[shift-1:-1] = spike_count_corr[shift:]
            spike_count_corr[-1:] = prev_del

    len_epoch = len(stim_inten)//n_repeats
    spike_counts_corrected = []
    errors_per_repeat      = []
    for i in range(n_repeats):
        errors_per_repeat.append(count_repl_in_range(frame_replacement, range(len_epoch*i, len_epoch*(i+1))))
        spike_counts_corrected.append(spike_count_corr[len_epoch*i:len_epoch*(i+1)])
    return np.array(spike_counts_corrected), np.array(errors_per_repeat)

# Cell
def removeSlowDrift(traces, fps=60, window=80, percentile=8):
    """
    Remove slow drifts from behavioral temporal traces such as locomotion speed obtained from the treadmill signal
    or pupil size obtained from the eye_tracking signal, by extracting a specified percentile within moving window from the signal.

    params:
        - traces: Behavioral temporal traces obtained from reM
        - fps: Sampling rate
        - window: Moving temporal window in seconds
        - percentile: Percentile to be extracted within moving window

    return:
        - Filtered temporal traces
    """
    smoothed = np.zeros(len(traces))
    n = round(window * fps)-1
    if n%2 == 0:
        n = n+1

    nBefore = math.floor((n-1)/2)
    nAfter = n - nBefore - 1

    for k in range(len(traces)):
        idx1 = max(np.array([0,k-nBefore]))
        idx2 = min(len(traces)-1,k+nAfter)
        tmpTraces = traces[idx1:idx2]
        smoothed[k] = np.percentile(tmpTraces, percentile)

    smoothed = savgol_filter(smoothed, n, 3)

    filteredTraces = traces - smoothed
    return filteredTraces

# Cell
def time_shift_test_corr(spike_counts, behav_signal, n_tests = 500, seed = 1):
    """
    Compute the null distribution of correlation between behavioral signal and spiking signal with a time shift test.

    params:
        - spike_counts: Array with spike counts for a specific neuron and data chunk from the reM
        - behav_signal: Array with behavioral signal for a specific neuron and data chunk from the reM
        - n_tests: number of used shifted signals to compute distribution
        - seed: seed for numpy function random.randint

    return:
        - null_dist_corr: Null distribution of correlation values
    """

    np.random.seed(seed)

    null_dist_corr=[]
    for i in range(n_tests):
        #Generate time-shifted behavioral test signal for shifts between 0.05*len(behav_signal) and len(behav_signal)
        test_behav_signal = np.roll(behav_signal, np.random.randint(len(behav_signal)*0.05, len(behav_signal)))
        # Compute Pearson's correlation with behavioral time-shifted test signal and spiking signal
        null_dist_corr.append(scipy.stats.pearsonr(test_behav_signal, spike_counts)[0])

    return null_dist_corr

# Cell
def cross_corr_with_lag(spike_counts, behav_signal, behav, conversion_factor_treadmill=None, removeslowdrift=True, fps=60, seconds=30):
    """
    Compute cross-correlation with lag between behavioral signal and spiking signal.
    Process signals, compute null distribution of the correlation with a time shift test and values .
    Return cross-correlation array, null-distribution array and values for plotting.

    params:
        - spike_counts: Array with spike counts for a specific neuron and data chunk from the reM
        - behav_signal: Array with behavioral signal for a specific neuron and data chunk from the reM
        - behav : String with name of behavioral signal to be analysed
        - conversion_factor : The value to convert the treadmill signal into cm/s
        - removeslowdrift: Boolean:
            False - doesn't remove slow drifts from the signal
            True - removes slow drifts by extracting a specified percentile within moving window from the signal
        - fps: Sampling rate
        - seconds: Window in seconds of the correlation lag

    return:
        - crosscorr: Cross-correlation with lag array between behavioral signal and spiking signal
        - corr_peak: Cross-correlation value at peak synchrony between behavioral signal and spiking signal
        - p_value_peak: P-value of the peak cross-correlation value
        - offset_peak: Temporal offset of the peak synchrony between behavioral signal and spiking signal in seconds
        - null_dist_corr: Null distribution of correlation values (output of 'utils.cross_corr_with_lag')
    """

    if behav == "treadmill":
        #Convert treadmill signal to running speed (cm/s)
        behav_signal = behav_signal * conversion_factor_treadmill
        behav_signal_filtered = gaussian_filter(abs(behav_signal), sigma=60)
    else:
        behav_signal_filtered = gaussian_filter(behav_signal, sigma=60)

    #Convolve signals with gaussian window of 1 second/60 frame
    spike_counts_filtered = gaussian_filter(spike_counts, sigma=60)

    if removeslowdrift:
        #Remove slow drifts from treadmill, pupil size and spiking signal
        spike_counts_detrend = removeSlowDrift(spike_counts_filtered, fps=60, window=100, percentile=8)
        behav_signal_detrend = removeSlowDrift(behav_signal_filtered, fps=60, window=100, percentile=8)
    else:
        spike_counts_detrend = spike_counts_filtered
        behav_signal_detrend = behav_signal_filtered

    #Get null distribution for correlation between behav_signal and spike_counts signal
    null_dist_corr = time_shift_test_corr(spike_counts_detrend, behav_signal_detrend, n_tests = 500)

    #Compute cross-correlation with lag and values to plot
    d1 = pd.Series(behav_signal_detrend)
    d2 = pd.Series(spike_counts_detrend)
    crosscorr = [d1.corr(d2.shift(lag)) for lag in range(-int(seconds*fps),int(seconds*fps+1))]
    offset_peak = np.around((np.ceil(len(crosscorr)/2)-np.argmax(abs(np.array(crosscorr))))/fps, decimals=3)
    corr_peak = np.max(abs(np.array(crosscorr)))
    p_value_peak = round((100-scipy.stats.percentileofscore(abs(np.array(null_dist_corr)), abs(corr_peak), kind='strict'))/100,2)

    return crosscorr, corr_peak, p_value_peak, offset_peak, null_dist_corr

# Cell
def get_inception_generator(imageset_folder, len_set=25, width=500, height=281):
    """
    Return a function to obtain inception loop images from their index.

    params:
        - imageset_folder: Path to the folder of the image sets
        - len_set: Number of images concatenated per set
        - width: image width
    return:
        - Function to obtain inception loop images from their index.
    """
    imageset_l = []
    paths = glob.glob(os.path.join(imageset_folder,"*.jpg"))
    paths_sorted = sorted(paths, key=lambda i: int(os.path.splitext(os.path.basename(i))[0].split("_")[-1]))

    for fn in paths_sorted: #Images accepted have the dimension (375,500)
        image = np.array(Image.open(fn))
        imageset_l.append(image)

    def image_yield(idx):
        if idx==-1:
            return np.zeros((height, width))+128
        set_idx = idx//25
        img_idx = idx%25
        return imageset_l[set_idx][:,width*img_idx:width*(img_idx+1), 1] #Returns a gray image

    return image_yield

# Cell
def group_omitted_epochs(stim_inten, spike_counts, n_fr_flash=4, n_fr_interflash=4, n_fr_isi=100):
    """
    Group the cells reponse to the different omitted stimulus epochs conditions (n_flashes)

    params:
        - stim_inten: The intensities of the omitted stimulus in shape (t)
        - spike_counts: Spikes counts of the cells in shape (t, n_cell)
        - n_fr_flash: Duration of a flash (ON flash during OFF baseline, OFF flash during ON baseline)
        - n_fr_interflash: Number of frames between two flashes (during an epoch)
        - n_fr_isi: Number of frames between two epochs
    return:
        - response_d_ON, response_d_OFF: Dictionnaries of the cells responses for different number of flashes repetions. Each contain an array of shape (n_cell, n_repeats, len_epoch+n_fr_isi).
    """
    starts_ON    = []
    stops_ON     = []
    n_flashes_ON = []

    counter   = 1
    i         = 0
    starts_ON.append(i)
    while i < len(stim_inten)-(n_fr_flash+n_fr_interflash):
        if stim_inten[i+(n_fr_flash*2+n_fr_interflash)]:
            break
        if stim_inten[i+(n_fr_flash+n_fr_interflash)]:
            counter += 1
            i+=(n_fr_flash+n_fr_interflash)
        else:
            stops_ON.append(i+(n_fr_flash+n_fr_interflash))
            n_flashes_ON.append(counter)
            counter = 1
            i += (n_fr_flash+n_fr_interflash+n_fr_isi)
            starts_ON.append(i)

    #Switching to the omitted OFF
    starts_OFF    = [starts_ON.pop()]
    stops_OFF     = []
    n_flashes_OFF = []
    while i < len(stim_inten)-(n_fr_flash+n_fr_interflash):
        if stim_inten[i+(n_fr_flash*2+n_fr_interflash)]==0:
            counter += 1
            i+=(n_fr_flash+n_fr_interflash)
        else:
            stops_OFF.append(i+(n_fr_flash+n_fr_interflash))
            n_flashes_OFF.append(counter)
            counter = 1
            i += (n_fr_flash+n_fr_interflash+n_fr_isi)
            starts_OFF.append(i)
    starts_OFF.pop()

    starts_ON     = np.array(starts_ON)
    stops_ON      = np.array(stops_ON)
    n_flashes_ON  = np.array(n_flashes_ON)
    starts_OFF    = np.array(starts_OFF)
    stops_OFF     = np.array(stops_OFF)
    n_flashes_OFF = np.array(n_flashes_OFF)

    response_d_ON, response_d_OFF = {}, {}
    for n_repeat in set(n_flashes_ON):
        where_cond = np.where(n_flashes_ON==n_repeat)[0]
        tmp        = np.array([spike_counts[start:stop+n_fr_isi] for start, stop in zip(starts_ON[where_cond],
                                                                                  stops_ON[where_cond])])
        response_d_ON[n_repeat] = np.transpose(tmp, (2, 0, 1))
    for n_repeat in set(n_flashes_OFF):
        where_cond = np.where(n_flashes_OFF==n_repeat)[0]
        tmp        = np.array([spike_counts[start:stop+n_fr_isi] for start, stop in zip(starts_OFF[where_cond],
                                                                                  stops_OFF[where_cond])])
        response_d_OFF[n_repeat] = np.transpose(tmp, (2, 0, 1))

    return response_d_ON, response_d_OFF

# Cell
def get_shank_channels(channel_positions, shank_dist_th=80):
    """
    Group the channels of a Buzsaki32 silicone probe into their shanks
    from the channel position.

    params:
        - channel_positions: List of channel positions
        - shank_dist_th: Distance between channels in X to rule if on same shank or not

    return:
        - array of grouped channel index of shape (n_shank(4), n_channel(8))
    """
    found      = np.zeros(len(channel_positions))
    shank_pos  = []
    chann_pos  = []

    while not np.all(found):
        next_idx   = np.argmin(found)
        next_pos   = channel_positions[next_idx][0] #getting the X position of the electrode
        this_shank = np.where(np.abs(channel_positions[:,0]-next_pos)<shank_dist_th)[0]
        chann_pos.append(this_shank)
        shank_pos.append(next_pos)
        found[this_shank] = 1

    shanks_idx = np.zeros((len(shank_pos), len(this_shank)), dtype=int) - 1 #Initialize with -1 in case of channel missing
    for i, order in enumerate(np.argsort(shank_pos)):
        shanks_idx[i,:len(chann_pos[order])] = chann_pos[order]
    return shanks_idx

# Cell
def format_pval(pval, significant_figures=2):
    """
    Helper function to format pvalue into string.
    """
    return '{:g}'.format(float('{:.{p}g}'.format(pval, p=significant_figures)))

# Cell
def stim_recap_df(reM):
    """
    Extract stimuli parameters (originally from the Database) to put them into a
    dataframe that will be displayed in the recapitulation plot.

    params:
        - reM: RecordMaster to extract stimuli parameters from

    return:
        - dataframe with the stimuli important informations
    """
    def parse_stim(stim_dc):
        param_d = {}
        param_d["hash"]        = stim_dc.attrs["md5"][:10] #the first 10 letters are more than enough
        param_d["n frames"]    = len(stim_dc)
        param_d["stimulus"]    = stim_dc.attrs["name"]

        if stim_dc.attrs["name"] in ["checkerboard", "fullfield_flicker", "flickering_bars", "flickering_bars_pr"]:
            param_d["frequency"] = stim_dc.attrs["refresh_rate"]
        elif stim_dc.attrs["name"] in ["chirp_am","chirp_fm","chirp_freq_epoch", "chirp_co"]:
            param_d["n ON"]      = int(stim_dc.attrs["tSteadyON_s"]*60)
            param_d["n OFF"]     = int(stim_dc.attrs["tSteadyOFF_s"]*60)
            param_d["n repeats"] = int(stim_dc.attrs["n_repeat"])
            if stim_dc.attrs["name"] in ["chirp_am","chirp_co"]:
                param_d["frequency"] = stim_dc.attrs["contrast_frequency"]
            elif stim_dc.attrs["name"]=="chirp_fm":
                param_d["frequency"] = stim_dc.attrs["max_frequency"]
            elif stim_dc.attrs["name"]=="chirp_freq_epoch":
                param_d["frequency"] = str([round(60/nfr,2) for nfr in dc.attrs["n_frame_cycle"]])
        elif stim_dc.attrs["name"] in ["fullfield_color_mix"]:
            param_d["n ON"]      = int(stim_dc.attrs["n_frame_on"])
            param_d["n OFF"]     = int(stim_dc.attrs["n_frame_off"])
            param_d["n repeats"] = int(stim_dc.attrs["n_repeat"])
        elif stim_dc.attrs["name"]=="moving_gratings":
            param_d["n repeats"]           = stim_dc.attrs["n_repeat"]
            param_d["n ON"]                = stim_dc.attrs["n_frame_on"]
            param_d["n OFF"]               = stim_dc.attrs["n_frame_off"]
            param_d["speeds"]              = stim_dc.attrs["speeds"]
            param_d["spatial frequencies"] = stim_dc.attrs["spatial_frequencies"]

        if "frame_replacement" in stim_dc.attrs:
            param_d["total drop"] = len(stim_dc.attrs["frame_replacement"])
        if "signal_shifts" in stim_dc.attrs:
            shift = 0
            for _, which_shift in stim_dc.attrs["signal_shifts"]:
                if which_shift=="ins":
                    shift += 1
                elif which_shift=="del":
                    shift -= 1
            param_d["total shift"] = shift

        return param_d

    series = []
    for seq in reM._sequences:
        for k, dc_l in seq:
            dc = dc_l[0]
            if dc.group == "stim":
                series.append(parse_stim(dc))
    df = pd.DataFrame.from_records(series, columns=["stimulus", "hash", "n frames", "n repeats",
                               "frequency", "n ON", "n OFF", "speeds", "spatial frequencies",
                              "total shift", "total drop"])
    df = df.fillna("")
    return df