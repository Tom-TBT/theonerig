# AUTOGENERATED! DO NOT EDIT! File to edit: 00_core.ipynb (unless otherwise specified).

__all__ = ['DataChunk', 'ContiguousRecord', 'RecordMaster', 'Data_Pipe', 'export_record', 'import_record']

# Cell
import h5py
import json, re
import numpy as np
from collections import namedtuple
from typing import Dict, Tuple, Sequence, Union
import itertools
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

class DataChunk(np.ndarray):
    """Base brick of data. Derived from np.ndarray
    params:
        - data: The ndarray with shape (time, ...)
        - idx: Index of the start of the DataChunk in the record.
        - group: group of the DataChunk in {stim, sync, cell, data}
        - fill: Default filling value."""
    def __new__(cls, data, idx, group, fill=0):
        # See https://docs.scipy.org/doc/numpy-1.11.0/user/basics.subclassing.html#basics-subclassing
        # for explanation on subclassing numpy arrays
        obj = np.asarray(data).view(cls)
        obj.idx = idx
        obj.group = group
        obj.fill = fill

        obj.attrs = {}

        return obj

    def __array_finalize__(self, obj):
        if obj is None: return
        self.idx   = getattr(obj, 'idx', None)
        self.group = getattr(obj, 'group', None)
        self.fill  = getattr(obj, 'fill', 0)
        self.attrs = getattr(obj, 'attrs', {})


    @property
    def range(self):
        return range(self.idx, self.idx + len(self))

    @property
    def slice(self):
        return slice(self.idx, self.idx + len(self))

    def __str__(self):
        return ("Group: "+str(self.group)
                +"\nStarting index: "+str(self.idx)
                +"\nFilling value: "+str(self.fill)
                +"\n"+super().__str__())

    def __repr__(self):
        return "DataChunk(%s,%s,%s,%s)"%(self.shape, self.idx, self.group, self.fill)

# Cell
class ContiguousRecord():
    """Representation of a contiguous recording session to store DataChunk
    of various sources under a single time reference. DataChunk are stored
    under a name in one of the groups "sync","stim","data" and "cell".

    A name can contain multiple DataChunk if those are not overlapping in time.

    Each ContiguousRecord contains in the group "sync" two master DataChunk,
    one for signals to be recorded across acquisition device to syncronize them,
    one for timepoints of these signals for the main device and are called
    respectively "signals" and "main_tp".

    """
    MAIN_TP = "main_tp"
    SIGNALS = "signals"
    def __init__(self, length:int, signals:DataChunk, main_tp:DataChunk, frame_rate:int=60 ):
        """Instanciate a ContiguousRecord.

        Parameters:
            - length (int): Number of bins of this record
            - signals (DataChunk): Signals for this record
            - main_tp (DataChunk): Timepoints of the signals for the main device
            - frame_rate(int): Frame rate in Hz
        """
        self.length = length
        self._frame_time = 1/frame_rate
        self._data_dict = {}

        self[self.SIGNALS] = signals
        self[self.MAIN_TP] = main_tp

        self._slice = slice(0,self.length,1)

    def dataset_intersect(self, existing_datachunk:list, new_datachunk:DataChunk):
        """Check for timepoint intersections of two DataChunks"""
        range_new = set(new_datachunk.range)
        intersect = False
        for range_existing in existing_datachunk:
            intersect |= len(range_new.intersection(range_existing.range)) > 0
        return intersect

    def keys(self):
        """Retrieves the existing keyys inside this ContiguousRecord"""
        return self._data_dict.keys()

    def get_slice(self, datachunk_name:str) -> list:
        """Returns the slices of the DataChunk corresponding to the given key"""
        if datachunk_name in self._data_dict.keys():
            return [chunk.slice for chunk in self._data_dict[datachunk_name]]
        else:
            return []

    def set_slice(self, slice_):
        """Set the slice to restrict the size of the DataChunk returned"""
        if slice_ is None:
            self._slice = slice(0,self.length,1)
        else:
            start, stop, step = slice_.start, slice_.stop, slice_.step
            if start is None:
                start = 0
            if stop is None:
                stop = self.length
            if step is None:
                step = 1
            if step!=1:
                print("Step in slice is currently not supported.")
                self._slice = slice(0,self.length,1)
            else:
                self._slice = slice(start,stop,step)


    def get_names_group(self, group_name:str) -> list:
        names = []
        for key, dChunk_l in self._data_dict.items():
            if dChunk_l[0].group == group_name:
                names.append(key)
        return names

    def to_s(self, n_frame):
        return round(self._frame_time*n_frame,2)

    def to_time_str(self, n_frame):
        s = int(self.to_s(n_frame))
        m, s = s//60, str(s%60)
        h, m = str(m//60), str(m%60)
        return "{0}:{1}:{2}".format('0'*(2-len(h))+h, '0'*(2-len(m))+m, '0'*(2-len(s))+s)

    def __len__(self):
        return self.length

    def __setitem__(self, key, value:DataChunk):
        if isinstance(key, str):
            if key not in self._data_dict.keys():
                self._data_dict[key] = []

            if not self.dataset_intersect(self._data_dict[key], value):
                self._data_dict[key].append(value)
            else:
                raise ValueError("Data with the same name already exists and intersect with the one provided")
        else:
            raise KeyError("Cannot set data with an integer index, it needs a name")

    def __getitem__(self, key):
        if isinstance(key, str):
            l_datachunk = self._data_dict[key]
            fill_value  = l_datachunk[0].fill
            shape       = l_datachunk[0].shape

            full_sequence = DataChunk(np.zeros((len(range(*self._slice.indices(self.length))), *shape[1:]),
                                               dtype=l_datachunk[0].dtype)+fill_value,
                                      self._slice.start if self._slice.start is not None else 0,
                                      fill_value)
            for datachunk in l_datachunk:
                dc_slice = datachunk.slice
                if dc_slice.start>=self._slice.stop or dc_slice.stop<=self._slice.start:
                    continue

                start = max(dc_slice.start, self._slice.start) #flooring to the maximum of both start
                stop  = min(dc_slice.stop, self._slice.stop) # and capping to the min of both end

                new_dc_slice  = slice(start-datachunk.idx, stop-datachunk.idx)
                res_start = self._slice.start if self._slice.start is not None else 0
                res_slice = slice(start-res_start, stop-res_start)
                full_sequence[res_slice] = datachunk.data[new_dc_slice]
                full_sequence.attrs.update(datachunk.attrs)

            return full_sequence

    def __iter__(self):
        groups = {"sync":[],"stim":[],"data":[],"cell":[]}
        for key, dChunk_l in self._data_dict.items():
            groups[dChunk_l[0].group].append((dChunk_l[0].idx, key))

        self._iter_order = []
        for group_name in ["sync","stim","data","cell"]:
            sorted_ = sorted(groups[group_name], key=lambda e:(e[0],))
            self._iter_order.extend([key for _, key in sorted_])
        self._n = 0

        return self

    def __next__(self):
        if self._n < len(self._iter_order):
            key = self._iter_order[self._n]
            dChunk_l = self._data_dict[key]
            self._n += 1
            return (key, dChunk_l)
        else:
            raise StopIteration

    def __delitem__(self, key):
        del self._data_dict[key]

    def __str__(self):
        res = "ContiguousRecord:\n"
        for k,v in self._data_dict.items():
            res += k+" : "+" ".join([str(dc.shape) for dc in v]) +"\n"
        return res

    def __repr__(self):
        return self._data_dict.__repr__()

    def __delete__(self, instance):
        for k, v in self._data_dict.items():
            del v
            self._data_dict[k] = None

# Cell
class RecordMaster(list):
    """
    The RecordMaster class is the top level object managing all
    timeseries. It uses a list of ContiguousRecord to represent
    possible discontinuted data records.

    The main aim of the RecordMaster is to store the various data
    stream of an experiment under a unique time reference, to ease
    the processing of the data.

    A RecordMaster is created by providing to it a list of (timepoints, signals) arrays of
    identical lenght. This serves as reference to align other DataChunks with the signals
    at the given timepoints. Multiple tuples represent uncontiguous sequences of data in
    a same record. The timepoints must be evenly spaced (regular).

    params:
        - reference_data_list: list of (timepoints, signals) arrays.
        - frame_rate: Frame rate in Hz, or list of frame rates matching len(reference_data_list)
    """

    def __init__(self, reference_data_list: Sequence[Tuple[DataChunk, DataChunk]], frame_rate=60):

        if not hasattr(frame_rate, '__iter__'):
            frame_rate = [frame_rate]*len(reference_data_list)

        self._sep_size   = 1000 #Used for the plotting of multiple sequences
        self._sequences = []
        for (ref_timepoints, ref_signals), fr in zip(reference_data_list, frame_rate):
            cs = ContiguousRecord(len(ref_timepoints), ref_signals, ref_timepoints, fr)
            self._sequences.append(cs)

    def set_datachunk(self, dc:DataChunk, name:str, sequence_idx=0):
        """Set the given DataChunk dc for the sequence at sequence_idx under name."""
        self._sequences[sequence_idx][name] = dc

    def append(self, ref_timepoints:DataChunk, ref_signals:DataChunk, frame_rate=60):
        cs = ContiguousRecord(len(ref_timepoints), ref_signals, ref_timepoints, frame_rate)
        self._sequences.append(cs)

    def insert(self, idx:int, ref_timepoints:DataChunk, ref_signals:DataChunk, frame_rate=60):
        cs = ContiguousRecord(len(ref_timepoints), ref_signals, ref_timepoints, frame_rate)
        self._sequences.insert(idx, cs)

    def keys(self):
        keys = []
        for seq in self._sequences:
            keys.extend(list(seq.keys()))
        return set(keys)

    def __setitem__(self, key, value:DataChunk):
        """Setting an item directly to the record_master place it in the first sequence"""
        if isinstance(key, str):
            self._sequences[0][key] = value

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            return self._sequences[key]
        elif isinstance(key, str):
            #We want all the data of that name
            res = []
            for seq in self._sequences:
                res.append(seq[key])
            return res

        raise TypeError("Indexing not understood")

    def __iter__(self):
        self._n = 0
        return self

    def __next__(self):
        if self._n < len(self):
            res = self._sequences[self._n]
            self._n += 1
            return res
        else:
            raise StopIteration

    def __len__(self):
        return len(self._sequences)

    def plot(self, ax=None, show_time=True, sort_by_name=False):
        colors = {"sync":"cornflowerblue", "stim":"orange", "data":"yellowgreen", "cell":"plum"}
        if ax is None:
            fig, ax = plt.subplots(figsize=(10, 5))
        ax.invert_yaxis()
        ax.xaxis.set_visible(False)

        #A first iteration through the ContiguousRecords to have all the DataChunk for the sorting
        groups = {"sync":[],"stim":[],"data":[],"cell":[]}
        frame_times = []
        for seq in self._sequences:
            frame_times.append(seq._frame_time)
            for name, dChunk_l in seq:
                dc = dChunk_l[0]
                if name not in groups[dc.group]:
                    groups[dc.group].append(name)

        all_names = []
        y_pos_dict = {}
        y_count    = 0
        for group_name in ["sync","stim","data","cell"]:
            if sort_by_name:
                groups[group_name].sort()
            all_names += groups[group_name]
            for dc_name in groups[group_name]:
                y_pos_dict[dc_name] = y_count
                y_count+=1

        frametime_ratios = [fr_t/max(frame_times) for fr_t in frame_times]
        cursor = 0
        for i, seq in enumerate(self._sequences):
            fr_ratio = frametime_ratios[i]
            for name, dChunk_l in seq:
                y_pos = y_pos_dict[name]
                for dChunk in dChunk_l:
                    pos = dChunk.idx + cursor
                    ax.barh(y_pos, len(dChunk)*fr_ratio, left=pos*fr_ratio, height=0.8, color=colors[dChunk.group], label=dChunk.group)
                    if show_time:
                        x = pos + len(dChunk)/2
                        text = "{0} -> {1} ".format(seq.to_time_str(dChunk.idx), seq.to_time_str(dChunk.idx+len(dChunk)))
                        ax.text(x*fr_ratio, y_pos, text, ha='center', va='center')
            cursor += (len(seq))*fr_ratio + self._sep_size

        legend_elements = [Patch(facecolor=colors["sync"],label='Synchro'),
                           Patch(facecolor=colors["data"],label='Data'),
                           Patch(facecolor=colors["stim"],label='Stimulus'),
                           Patch(facecolor=colors["cell"],label='Cell'),]
        ax.legend(handles=legend_elements, ncol=5, bbox_to_anchor=(0, 1), loc='lower left', fontsize='small')
        ax.set_yticks(range(len(all_names)))
        ax.set_yticklabels(all_names)
        ax.set_xlim(-100,cursor)

    def __str__(self):
        return "["+",\n".join([repr(seq) for seq in self._sequences])+"]"

    def __repr__(self):
        return "["+", ".join([repr(seq) for seq in self._sequences])+"]"

    def __delete__(self, instance):
        for seq in self._sequences:
            del seq

# Cell
class Data_Pipe():
    """
    A Data_Pipe is used to query data from a RecordMaster. By adding/substracting portions
    of the record using DataChunk names, it creates a mask over which specified DataChunks
    are retrivied as a dictionary from the Data_Pipe.

    params:
        - record_master: the RecordMaster from which to retrieve data
        - data_names: Name, or list of names of the DataChunk to retrieve once the masking process is done.
        - target_names: Alias, or list of alias to give to the DataChunk in the retrieved dictionnary.
        - cast_to_np: boolean to cast the piped data into a numpy array. Can be set directly too in self.cast_to_np
    """
    def __init__(self, record_master:RecordMaster, data_names:Union[str,list], target_names:Union[str,list]=None, cast_to_np=False):
        self.record_master = record_master
        if isinstance(data_names, str):
            data_names = [data_names]

        if isinstance(target_names, str):
            target_names = [target_names]

        if target_names is None:
            target_names = data_names
        elif len(data_names) != len(target_names):
            raise Exception("data_names and target_names length must match")

        self.target_names = target_names
        self.data_names   = data_names
        self._masks       = [np.zeros(len(seq), dtype=bool) for seq in record_master]
        self._slices      = []

        self.cast_to_np   = cast_to_np

    def plot(self, newfig=False):
        """
        Add the mask of the Pipe to a RecordMaster plot.
        Usage:
            reM.plot()
            pipe.plot()
        """
        factor = -1
        if newfig:
            plt.figure()
            factor = 1
        cursor = 0
        frame_times      = [seq._frame_time for seq in self.record_master._sequences]
        frametime_ratios = [fr_t/max(frame_times) for fr_t in frame_times]
        for i, seq in enumerate(self.record_master):
            fr = frametime_ratios[i]
            x  = np.linspace(cursor, cursor+len(seq)*fr, len(seq), endpoint=False)
            plt.plot(x, self._masks[i]*factor-1, c='tab:blue')
            cursor += len(seq)*fr + self.record_master._sep_size

    def copy(self):
        """
        Duplicate the Pipe and its mask, and return the new pipe.
        """
        new_pipe =  Data_Pipe(record_master=self.record_master,
                         data_names=self.data_names,
                         target_names=self.target_names)
        new_pipe._masks = np.copy(self._masks)
        new_pipe._slices = self._slices.copy()
        return new_pipe

    def _get_dchunk_names(self, names):
        if isinstance(names, str):
            names = [names]
        dchunk_name = []
        for seq in self.record_master:
            for name in names:
                if name in ["sync", "cell", "data", "stim"]:
                    dchunk_name.extend(seq.get_names_group(name))
                else:
                    dchunk_name.append(name)
        return list(set(dchunk_name))

    def _intersect_names(self):
        for i, seq in enumerate(self.record_master):
            for name in self.data_names:
                if name not in seq.keys():
                    self._masks[i] = np.zeros(len(seq), dtype=bool)
                    break

    def _update_slices(self):
#         self._intersect_names() #Always intersect the names we wanna retrieve ? Might be not needed (even cause bug)
        self._slices = []
        #Iterating the list of mask (one per seq of the record_master)
        for j, mask in enumerate(self._masks):
            seq = self.record_master[j]
            mask = np.concatenate(([0],mask,[0])) #Putting zeros on the side in case the limits would be ones
            for start, stop in np.where(mask[1:]-mask[:-1])[0].reshape(-1,2):#Split the mask where 0 separates the 1
                self._slices.append((j, slice(start,stop)))

    def __ior__(self, names:Union[str, list]):
        return self.__iadd__(names)
    def __or__(self, names:Union[str, list]):
        return self.copy().__ior__(names)

    def __iand__(self, names:Union[str, list]):
        dchunk_name = self._get_dchunk_names(names)
        for i, seq in enumerate(self.record_master):
            new_mask = np.zeros(len(seq), dtype=bool)
            for name in dchunk_name:
                for slice_ in seq.get_slice(name):
                    new_mask[slice_] = 1
            self._masks[i] &= new_mask
        self._update_slices()
        return self
    def __and__(self, names:Union[str, list]):
        return self.copy().__iand__(names)

    def __ixor__(self, names:Union[str, list]):
        dchunk_name = self._get_dchunk_names(names)
        for i, seq in enumerate(self.record_master):
            new_mask = np.zeros(len(seq), dtype=bool)
            for name in dchunk_name:
                for slice_ in seq.get_slice(name):
                    new_mask[slice_] = 1
            self._masks[i] ^= new_mask
        self._update_slices()
        return self
    def __xor__(self, names:Union[str, list]):
        return self.copy().__ixor__(names)

    def __iadd__(self, names:Union[str, list]):
        dchunk_name = self._get_dchunk_names(names)
        for i, seq in enumerate(self.record_master):
            for name in dchunk_name:
                for slice_ in seq.get_slice(name):
                    self._masks[i][slice_] = 1
        self._update_slices()
        return self
    def __add__(self, names:Union[str, list]):
        return self.copy().__iadd__(names)

    def __isub__(self, names:Union[str, list]):
        dchunk_name = self._get_dchunk_names(names)
        for i, seq in enumerate(self.record_master):
            for name in dchunk_name:
                for slice_ in seq.get_slice(name):
                    self._masks[i][slice_] = 0
        self._update_slices()
        return self
    def __sub__(self, names:Union[str, list]):
        return self.copy().__isub__(names)

    def __iter__(self):
        self._n = 0
        return self

    def __next__(self):
        if self._n < len(self):
            res = {}
            seq_idx, _slice = self._slices[self._n]
            self.record_master[seq_idx].set_slice(_slice)
            for i, name in enumerate(self.data_names):
                if self.cast_to_np:
                    res[self.target_names[i]] = np.array(self.record_master[seq_idx][name])
                else:
                    res[self.target_names[i]] = self.record_master[seq_idx][name]
            self.record_master[seq_idx].set_slice(None)
            self._n += 1
            return res
        else:
            raise StopIteration

    def __len__(self):
        return len(self._slices)

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            seq_idx, _slice = self._slices[key]
            self.record_master[seq_idx].set_slice(_slice)
            res = {}
            for i, name in enumerate(self.data_names):
                if self.cast_to_np:
                    res[self.target_names[i]] = np.array(self.record_master[seq_idx][name])
                else:
                    res[self.target_names[i]] = self.record_master[seq_idx][name]
            self.record_master[seq_idx].set_slice(None)
            return res
        elif isinstance(key, slice):
            l_res = []
            for seq_idx, _slice in self._slices[key]:
                res = {}
                for i, name in enumerate(self.data_names):
                    if self.cast_to_np:
                        res[self.target_names[i]] = np.array(self.record_master[seq_idx][name][_slice])
                    else:
                        res[self.target_names[i]] = self.record_master[seq_idx][name][_slice]

                l_res.append(res)
            return l_res
        else:
            raise IndexError ("only integers and slices (`:`) are valid indices")

    def __str__(self):
        return "(datachunks, targets, slices), "+self.__repr__()

    def __repr__(self):
        return "Pipe(%s)"%(repr(self.data_names)+", "+repr(self.target_names)+", "+repr(self._slices))

# Cell
def export_record(path, record_master):
    """Export a Record_Master object to an h5 file, readable outside of this library.

    params:
        - path: path of the file to be saved
        - record_master: RecordMaster to save
    """
    print("Exporting the record master")
    with h5py.File(path, mode="w") as h5_f:
        fr = None
        if hasattr(record_master, '_frame_time'):
            fr = record_master._frame_time #_frame_time was moved to Contigous_Record
        h5_f.attrs["_sep_size"]   = record_master._sep_size
        for i, contig in enumerate(record_master):
            #create contig
            print("Contiguous sequence",i)
            cntig_ref = h5_f.create_group(str(i))
            cntig_ref.attrs["length"] = contig.length
            if fr is not None:
                cntig_ref.attrs["_frame_time"] = fr
            else:
                cntig_ref.attrs["_frame_time"] = contig._frame_time
            for key, dc_list in contig._data_dict.items():
                #create datastream
                print("...Entering stream",key)
                stream_ref = cntig_ref.create_group(key)
                for datachunk in dc_list:
                    print("......",str(datachunk.idx)+"->"+str(datachunk.idx+len(datachunk)))
                    dset = stream_ref.create_dataset(str(datachunk.idx), data=np.array(datachunk), compression="gzip", compression_opts=4)
                    for attr_k, attr_v in datachunk.attrs.items():
                        dset.attrs[attr_k] = json.dumps(attr_v)
                    dset.attrs["__fill"] = datachunk.fill
                    dset.attrs["__group"] = datachunk.group
    print()

def import_record(path):
    """Import a Record_Master from an h5 file saved by the export_record function of this library.

    params:
        - path: path of the RecordMaster to import
    """
    print("Importing the record master")
    with h5py.File(path, mode="r") as h5_f:
        record_master    = None
        frame_rate = None
        reg         = re.compile("frame_time")
        fr_time_key = list(filter(reg.search, h5_f.attrs.keys()))
        if len(fr_time_key)==1:
            frame_rate = round(1/h5_f.attrs[fr_time_key[0]])
        for j, key_contig in enumerate(h5_f.keys()):
            ref_contig = h5_f[key_contig]
            stream_d   = {}
            keys = sorted(h5_f.keys(), key=int)
            for j, key_contig in enumerate(keys):
                ref_dstream = ref_contig[key_dstream]
                dchunk_l = []
                for key_dc in ref_dstream.keys():

                    data = ref_dstream[key_dc]
                    idx  = int(key_dc)
                    attrs = {}
                    for k,v in data.attrs.items():
                        if k not in  ["__fill", "__group"]:
                            attrs[k] = json.loads(v)
                        elif k == "__fill":
                            fill = v
                        elif k == "__group":
                            group = v
                    dchunk = DataChunk(data=data[:], idx=idx, group=group)
                    dchunk.attrs = attrs
                    dchunk_l.append(dchunk)

                stream_d[key_dstream] = dchunk_l
            if len(fr_time_key)==0:
                frame_rate = round(1/ref_contig.attrs["_frame_time"])
            if record_master is None:
                record_master = RecordMaster([(stream_d["main_tp"][0],stream_d["signals"][0])], frame_rate=frame_rate)
            else:
                record_master.append(stream_d["main_tp"][0],stream_d["signals"][0], frame_rate=frame_rate)
            for kstream, vstream in stream_d.items():
                for k, dc in enumerate(vstream):
                    if kstream in ["main_tp", "signals"] and k==0:
                        continue
                    record_master.set_datachunk(dc, name=kstream, sequence_idx=j)
    print()
    return record_master