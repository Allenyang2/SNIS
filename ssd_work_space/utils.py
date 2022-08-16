"""
Utility functions
"""
import numpy as np
import pandas as pd
import os
from bs4 import BeautifulSoup as bs
from collections import defaultdict
from bisect import insort
import matplotlib.pyplot as plt

plt.style.use('seaborn')


def drawCDF(data, label='$x$', max_p=1):
    """Draw CDF plot

    Args:
        data: list-like data structure containing data points
        label: string for the x label
"""
    y = np.linspace(0, max_p, len(data), endpoint=False)
    x = sorted(data)
    plt.plot(x, y)
    plt.xlabel(label)
    plt.ylabel("$p$")
    plt.grid(True)
    plt.show()


def roundList(data, precision=0):
    """Round the number in a list to a precision

    Args:
        data: list-like data structure containing float
        precision: the precision after the decimal point
"""
    return [round(d, precision) for d in data]


def getFlowMap(log_file, output):
    """Copy the flow-port mapping generated by network simulation to a csv file. This function is needed to get the mapping between the flow ID and the port number. The port number for each flow is unique in ns3-simulator.

    Args:
        log_file: the file path to read the log where containing the mapping data
        output: the output file path

    """
    with open(output, 'w') as of:
        with open(log_file, 'r') as f:
            line = f.readline().strip()
            # By default the mapping start with "Flow_ID,Port"
            while line and not line.startswith("Flow_ID,Port"):
                line = f.readline().strip()

            # "\n\n" will mark the end of the mapping data
            while line:
                of.write(line + "\n")
                line = f.readline().strip()


def readQueue(input_file=None, encoding="utf8"):
    """Read the queue.txt to extract PAUSE message

    Args:
        input_file: a string for the path of queue.txt
        encoding: the encoding type of the file. By default, windows uses utf16 and linux uses utf8

    Return:
        A queue dictionary, a PAUSE_R dictionary, and a PAUSE_S dictionary
        The key of each dictionary is the node ID and the value is a list containing the timestamp in nanosecond in ascending order
    """
    if not input_file:
        print("No input file\n")
        return None

    Q_dic = defaultdict(list)  # Queue length
    pr_dic = defaultdict(list)  # PAUSE receiver
    ps_dic = defaultdict(list)  # PAUSE sender

    with open(input_file, 'r', errors="ignore", encoding=encoding) as f:
        line = f.readline().strip()
        while line:
            arr = line.strip().split(" ")
            if len(arr) == 3 and arr[-1] == "PAUSE_R":
                # Format: Time Node PAUSE_R
                insort(pr_dic[int(arr[1])], int(arr[0]))
            elif len(arr) == 4:
                if arr[2] == "Queue":
                    # Format: Time Node QUEUE Q_len
                    insort(Q_dic[int(arr[1])], (int(arr[0]), int(arr[-1])))
                elif arr[2] == "PAUSE_S":
                    # Format: Time Node PAUSE_S Q_len
                    insort(ps_dic[int(arr[1])], (int(arr[0]), int(arr[-1])))

            line = f.readline()
    return Q_dic, pr_dic, ps_dic


def readFlows(path, time_unit=1e6, size_unit=1e3):
    """Read the flow_moniter.xml and return a list of flow summary

    Args:
        path: a string for the path
        time_unit: an int to transfer to ms from the original unit ns
        size_unit: an int to transfer to KB from the original unit Bytes
    """
    with open(path, 'r') as f:
        data = bs(f, 'xml')
    flows = data.FlowMonitor.FlowStats.findAll("Flow")
    ips = data.FlowMonitor.Ipv4FlowClassifier.findAll("Flow")

    # Extract the flow's identity information like source, destination address, port, etc
    flow_dic = {f['flowId']: f.attrs for f in flows}
    for ip in ips:
        flow_dic[ip['flowId']].update(ip.attrs)

    for f in flow_dic.values():
        # original format: "+123.1ns"
        f['timeFirstTxPacket'] = float(
            f['timeFirstTxPacket'][1:-2]) / time_unit
        f['timeLastRxPacket'] = float(f['timeLastRxPacket'][1:-2]) / time_unit
        f['delaySum'] = float(f['delaySum'][1:-2]) / time_unit
        f['jitterSum'] = float(f['jitterSum'][1:-2]) / time_unit
        f['txBytes'] = int(f['txBytes']) / size_unit  # The size unit is KB
        f['FCT'] = f['timeLastRxPacket'] - f['timeFirstTxPacket']

    fs = sorted([flow_dic[str(i)] for i in range(1,
                                                 len(flow_dic) + 1)],
                key=lambda f: f['txBytes'])
    return fs


def readSummary(path,
                map_file='flow_map.csv',
                fct_file='fct.csv',
                ssd_file='result.csv'):
    """Read and merge both SSD and network simulation data into one DataFrame

    Args:
        path: A string for the path to the the directory containing all log files

    Return:
        A DataFrame containing "RequestID,InitiatorID,TargetID,ArrivalTime,VolumeID,Offset,Size,IOType,DelayTime,FinishTime,Flow_ID,Port,FCT,TotalDelay"
    """
    map_dt = pd.read_csv(os.path.join(path, map_file))#, sep = ' ', names=['Flow_ID', 'Port'],on_bad_lines= 'skip')  # Flow_ID,Port
    fct_dt = pd.read_csv(os.path.join(path, fct_file))#, sep = ' ', names=['Port', 'FCT'])  # Port,FCT
    map_dt = map_dt.merge(fct_dt, how='left')
    ssd_dt = pd.read_csv(os.path.join(path, ssd_file))
    ssd_dt.RequestID -= ssd_dt.RequestID.min(
    )  # In case that the RequestID doesn't not start from 0
    for col in map_dt.columns:
        ssd_dt[col] = map_dt[col]
    ssd_dt['TotalDelay'] = ssd_dt.DelayTime + ssd_dt.FCT
    #print(ssd_dt)
    ssd_dt["Port"] = ssd_dt.Port.astype(int)

    return ssd_dt

def calculate_tpt_distance(tpt1, tpt2):
    """Calculate the relative difference of mean, median, and 90th of two throughput arrays.

    Args:
        tpt1/tpt2: two throughput arrays 

    Return:
        the relative difference of mean, median and 90th of arrays
    """
    def relative_distance(val1, val2):
        return abs(val1 - val2)/max(val1, val2)
        #return (val1 - val2)/max(val1, val2)
    return relative_distance(tpt1.mean(), tpt2.mean()), \
        relative_distance(tpt1.median(), tpt2.median()), \
        relative_distance(np.percentile(tpt1, 90), np.percentile(tpt2, 90))

def calculate_convergency_criteria(tpt1, tpt2, c_mean=1.0/3, c_median=1.0/3, c_90th=1.0/3):
    R_mean, R_median, R_90th = calculate_tpt_distance(tpt1, tpt2)
    return c_mean*R_mean + c_median*R_median + c_90th*R_90th