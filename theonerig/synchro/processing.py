# AUTOGENERATED! DO NOT EDIT! File to edit: 12_synchro.processing.ipynb (unless otherwise specified).

__all__ = ['get_thresholds', 'get_first_high', 'reverse_detection', 'extend_timepoints', 'detect_frames', 'error_check',
           'cluster_frame_signals', 'parse_time', 'get_position_estimate', 'match_starting_position', 'display_match',
           'frame_error_correction', 'error_frame_matches', 'apply_shifts', 'shift_detection_conv',
           'shift_detection_NW']

# Cell
import numpy as np
import datetime
import glob
import os

# Cell
def get_thresholds(data):
    max_val = max(data[len(data)//2:len(data)//2 + 10000000]) #Looking for a max in a portion of the data, from the middle
    high_thresh = max_val*3/4 # High threshold set at 3/4th of the max
    low_thresh  = max_val*1/4
    return low_thresh, high_thresh

# Cell
def get_first_high(data, threshold):
    if np.any(data>threshold):
        return np.argmax(data>threshold)
    else:
        return -1

def reverse_detection(data, frame_timepoints, low_threshold, increment):
    new_timepoints = []
    new_signals = []

    safe_increment = int(increment * 105/100)

    i = frame_timepoints[0]-safe_increment
    while i>0:
        data_slice = data[i:i+increment//2]
        if np.any(data_slice > low_threshold):
            i = i+np.argmax(data_slice > low_threshold)
        else:
            break #No low threshold crossing found -> no more frames to detect
        new_timepoints.append(i)
        i-= safe_increment #We move backward of almost a frame

    return new_timepoints[::-1]

def extend_timepoints(frame_timepoints, n=10):
    frame_timepoints = np.array(frame_timepoints)
    typical_distance = int(np.mean(np.diff(frame_timepoints)))
    extended_tp = [frame_timepoints[0]-(i+1)*typical_distance for i in range(n) if (frame_timepoints[0]-(i+1)*typical_distance)>0]
    return extended_tp[::-1]

def detect_frames(data, low_threshold, high_threshold, increment):
    frame_timepoints, frame_signals = [], []
    safe_increment = int(increment*95/100)

    first_high = get_first_high(data, high_threshold)
    if first_high == -1:
        print("No high frame detected. Detection can't work.")
        return

    frame_timepoints.append(first_high)
    frame_signals.append(1)

    new_timepoints   = reverse_detection(data, frame_timepoints, low_threshold, increment)
    new_extrapolated = extend_timepoints(new_timepoints)
    frame_timepoints = new_extrapolated + new_timepoints + frame_timepoints
    frame_signals    = [0]*(len(new_timepoints)+len(new_extrapolated)) + frame_signals

    i = first_high + safe_increment
    while i < len(data):
        data_slice = data[i:i+increment//2]
        if np.any(data_slice>low_threshold):
            i = i+np.argmax(data_slice>low_threshold)
        else:
            break #This frame sequence is over. Pass the next sequence through this function if there are frames left
        frame_timepoints.append(i)
        frame_signals.append(int(np.any(data_slice > high_threshold)))
        i += safe_increment

    frame_timepoints = np.array(frame_timepoints)
    frame_signals    = np.array(frame_signals)
    frame_timepoints = frame_timepoints - 3 # A slight shift of the timepoints
                                            # to include the begginning of the peaks.

    error_check(frame_timepoints)

#     self.frame_start_time = self.record_start_time + datetime.timedelta(0,int(self.frame_timepoints[0]/self.sampling_rate))
#     self.frame_end_time = self.record_start_time + datetime.timedelta(0,int(self.frame_timepoints[-1]/self.sampling_rate))

    return frame_timepoints, frame_signals

def error_check(frame_tp):
    deriv_frame_tp = np.diff(frame_tp)
    error_len_th = np.mean(deriv_frame_tp)+np.std(deriv_frame_tp)*6

    error_frames = np.abs(deriv_frame_tp)>error_len_th
    if np.any(error_frames):
        print("Error in timepoints detected in frames", np.where(error_frames)[0],
              "at timepoint", frame_tp[np.where(error_frames)[0]])

# Cell
def cluster_frame_signals(data, frame_timepoints, n_cluster=5):
    frame_aucs = np.fromiter(map(np.trapz, np.split(data, frame_timepoints)), float)
    if frame_timepoints[0] != 0: #We need to remove the first part if it wasn't a full frame
        frame_aucs = frame_aucs[1:]
    frame_auc_sorted = np.sort(frame_aucs)
    deriv = np.array(frame_auc_sorted[1:]-frame_auc_sorted[:-1])
    deriv[:5]  = 0 #removing tails values that can show weird stuff
    deriv[-5:] = 0
    threshold_peak = np.std(deriv)*3
    n          = n_cluster - 1
    idx_gaps = np.zeros(n+3, dtype="int")
    tmp_deriv = deriv.copy()
    for i in range(n+3): #Detecting more peaks than needed and then taking them starting on the right
        if tmp_deriv[np.argmax(tmp_deriv)] < threshold_peak:
            if i<n_cluster-1:
                print("Less transition in AUC detected than needed, results will be weird")
            break
        idx_gaps[i] = np.argmax(tmp_deriv)
        tmp_deriv[idx_gaps[i]] = 0
    idx_gaps = np.sort(idx_gaps)
    idx_gaps = idx_gaps[-4:]
    thresholds = np.zeros(n, dtype="float")
    for i, idx in enumerate(idx_gaps):
        thresholds[i] = (frame_auc_sorted[idx+1] + frame_auc_sorted[idx])/2

    return np.array([np.sum(auc>thresholds) for auc in frame_aucs], dtype=int)

# Cell
def parse_time(time_str, pattern="%y%m%d_%H%M%S"):
    return datetime.datetime.strptime(time_str, pattern)

def get_position_estimate(stim_time, record_time, sampling_rate):
    if stim_time < record_time:
        return -1
    else:
        return (stim_time - record_time).seconds * sampling_rate

# Cell
def match_starting_position(frame_timepoints, frame_signals, stim_signals, estimate_start):
    stim_matching_len = min(600, np.where(np.diff(stim_signals)!=0)[0][50]) #Way of getting the 50th change in the signals
    #But not higher than 600 (correspond to 10s, and is necessary for moving gratings)
#     stim_matching_len = 50
    idx_estimate = np.argmax(frame_timepoints>estimate_start)
    search_slice = slice(max(0, idx_estimate-1000), min(idx_estimate+1000, len(frame_signals)))
#     diff_signals = np.diff(frame_signals[search_slice])
#     diff_stim    = np.diff(stim_signals[:stim_matching_len])
#     return search_slice.start + np.argmax(np.correlate(diff_signals, diff_stim))
    return search_slice.start + np.argmax(np.correlate(frame_signals[search_slice],
                                                       stim_signals[:stim_matching_len]))

def display_match(match_position, reference=None, recorded=None, corrected=None, len_line=50):
    start, mid, end = 0, len(reference)//2, len(reference)-len_line
    for line in [start, mid, end]:
        if reference is not None:
            print("REF ["+str(line)+"] "," ".join(map(str,map(int, reference[line:line+len_line]))))
        if recorded is not None:
            print("REC ["+str(line)+"] "," ".join(map(str,map(int, recorded[line+match_position:line+len_line+match_position]))))
        if corrected is not None:
            print("COR ["+str(line)+"] "," ".join(map(str,map(int, corrected[line:line+len_line]))))
        print()

# Cell
def frame_error_correction(signals, unpacked, algo="nw"):
    if algo=="nw":
        shift_log = shift_detection_NW(signals.astype(int), unpacked[1].astype(int))
    elif algo=="conv":
        shift_log = shift_detection_conv(signals.astype(int), unpacked[1].astype(int), range_=5)
    intensity, marker, shader = apply_shifts(unpacked, shift_log)
    error_frames, replacements = error_frame_matches(signals, marker, range_=5)
    intensity[error_frames]    = intensity[replacements]
    marker[error_frames]       = marker[replacements]
    if shader is not None:
        shader[error_frames] = shader[replacements]
    return (intensity, marker, shader), shift_log, list(zip(map(int,error_frames), map(int,replacements)))

def error_frame_matches(signals, marker, range_):
    error_frames = np.nonzero(signals!=marker)[0]
    where_equal = [((np.where(marker[err_id-range_:err_id+(range_+1)] == signals[err_id])[0]) - range_) for err_id in error_frames]

    #filtering out the frames where no match was found
    tmp    = np.array([[wheq,err] for (wheq, err) in zip(where_equal, error_frames) if len(wheq)>0])
    where_equal  = tmp[:,0]
    error_frames = tmp[:,1]

    #Choosing among the equal frame signals the one that is the closest
    closest_equal = [wheq[(np.abs(wheq)).argmin()] for wheq in where_equal]

    error_frames = np.array(error_frames, dtype=int)
    replacements  = error_frames + np.array(closest_equal, dtype=int)

    return error_frames, replacements

def apply_shifts(unpacked, op_log):
    intensity, marker, shader = unpacked[0], unpacked[1], None
    if len(unpacked)==3:
        shader = unpacked[2]

    res_inten, res_marker = np.zeros(intensity.shape), np.zeros(marker.shape, dtype=int)
    res_shader=None
    if shader is not None:
        res_shader = np.zeros(shader.shape)
    cursor, shift = 0,0
    for idx, op in op_log:
        res_inten[cursor+shift:idx] = intensity[cursor:idx-shift]
        res_marker[cursor+shift:idx] = marker[cursor:idx-shift]
        if shader is not None:
            res_shader[cursor+shift:idx] = shader[cursor:idx-shift]
        if op=="ins": #We add the duplicated frame
            res_inten[idx]  = intensity[idx-1] #duplicating
            res_marker[idx] = marker[idx-1]
            if shader is not None:
                res_shader[idx] = shader[idx-1]
            shift += 1 #And incrementing index
        elif op=="del":
            shift -= 1
        cursor += len(marker[cursor:idx-shift])

    res_inten[cursor+shift:] = intensity[cursor:cursor+len(res_inten[cursor+shift:])]
    res_marker[cursor+shift:] = marker[cursor:cursor+len(res_marker[cursor+shift:])]
    if shader is not None:
        res_shader[cursor+shift:] = shader[cursor:cursor+len(res_shader[cursor+shift:])]

    return (res_inten, res_marker, res_shader)

def shift_detection_conv(signals, marker, range_):
    marker = marker.copy()
    shift_detected = True
    operation_log = []
    while shift_detected:
        error_frames, replacements = error_frame_matches(signals, marker, range_)

        all_shifts = np.zeros(len(marker))
        all_shifts[error_frames] = replacements-error_frames
        all_shifts_conv = np.convolve(all_shifts, [1/20]*20, mode="same") #Averaging the shifts to find consistant shifts

        shift_detected = np.any(np.abs(all_shifts_conv)>.5)
        if shift_detected: #iF the -.5 threshold is crossed, we insert a "fake" frame in the reference and we repeat the operation
            change_idx = np.argmax(np.abs(all_shifts_conv)>.5)
            if all_shifts_conv[change_idx]>.5:#Need to delete frame in reference
                #Need to refine index to make sure we delete a useless frame
                start,stop = max(0,change_idx-2), min(len(marker),change_idx+2)
                for i in range(start,stop):
                    if marker[i] not in signals[start:stop]:
                        change_idx = i
                        break
                operation_log.append([int(change_idx), "del"])
                marker = np.concatenate((marker[:change_idx], marker[change_idx+1:], [0]))
            else:#Need to insert frame in reference
                operation_log.append([int(change_idx), "ins"])
                #inserting a frame and excluding the last frame to keep the references the same length
                marker     = np.insert(marker, change_idx, marker[change_idx], axis=0)[:-1]
    return operation_log

def shift_detection_NW(signals, marker):
    """Memory optimized Needleman-Wunsch algorithm.
    Instead of an N*N matrix, it uses a N*(side*2+1) matrix. Indexing goes slightly differently but
    result is the same, with far less memory consumption and exection speed scaling better with
    size of the sequences to align."""
    #Setting the similarity matrix
    side = 20
    sim_mat = np.empty((len(marker), side*2+1), dtype="int32")
    #Setting the errors
    insertion_v = -10 #insertions are commons not so high penalty
    deletion_v  = -10 #deletions detection happens during periods of confusion but are temporary. High value
    error_match = np.array([1,-1,-3,-3,-1]) #The value for a 0 matching with [0,1,2,3,4]
    error_mat = np.empty((5,5))
    for i in range(5):
        error_mat[i] = np.roll(error_match,i)

    #Filling the similarity matrix
    sim_mat[0, side] = error_mat[marker[0], signals[0]]
    #Initialization: Setting the score of the first few row and first few column cells
    for j in range(side+1, side*2+1):
        sim_mat[0,j] = sim_mat[0,side] + insertion_v*j
    for i in range(1, side+1):
        sim_mat[i,side-i] = sim_mat[0,side] + deletion_v*i

    #Corpus: if j is the first cell of the row, the insert score is set super low
    #        if j is the last  cell of the row, the delete score is set super low
    for i in range(1, sim_mat.shape[0]):
        start = max(side-i+1, 0)
        stop  = min(side*2+1, side+sim_mat.shape[0]-i)
        for j in range(start, stop):
            if j==0:#j==start and i>side:
                insert = -99999
                delete = sim_mat[i-1, j+1] + deletion_v
            elif j==side*2:
                delete = -99999
                insert = sim_mat[i, j-1] + insertion_v
            else:
                insert = sim_mat[i, j-1] + insertion_v
                delete = sim_mat[i-1, j+1] + deletion_v
            match  = sim_mat[i-1, j] + error_mat[marker[i], signals[j+i-side]]
            sim_mat[i,j] = max(insert,delete,match)

    #Reading the similarity matrix
    #In general, it's the same, at the difference that when i decrement, must add 1 to j compared to usual.
    i = len(marker)-1
    j = side
    operation_log = []
    while (i > 0 or j>side-i):
        if (i > 0 and j>side-i and sim_mat[i,j]==(sim_mat[i-1,j]+error_mat[marker[i], signals[j+i-side]])):
            i -= 1
        elif(i > 0 and sim_mat[i,j] == sim_mat[i-1,j+1] + deletion_v):
            operation_log.insert(0,(i+1, "del")) #Insert at i+1 (and j+1 bello) showed better empirical results
            i-=1
            j+=1
        else:
            operation_log.insert(0,(j+i-side+1, "ins"))
            j-=1

    return operation_log