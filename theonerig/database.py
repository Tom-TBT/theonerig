# AUTOGENERATED! DO NOT EDIT! File to edit: 05_database.ipynb (unless otherwise specified).

__all__ = ['get_db_engine', 'get_record_essentials']

# Cell
from sqlalchemy import create_engine
from sqlalchemy import Table, Column, Integer, String, MetaData, select

import pandas as pd

# Cell
def get_db_engine(username, password, ip_adress, model_name, rdbms="mysql"):
    return create_engine("%s://%s:%s@%s/%s" % (rdbms, username, password, ip_adress, model_name),echo = False)

# Cell
def get_record_essentials(record_id, engine):
    q_select_record = "SELECT * FROM Record WHERE id = %d" % record_id
    q_select_cell = "SELECT * FROM Cell WHERE record_id = %d" % record_id

    df_record = pd.read_sql_query(q_select_record, engine)
    df_cell = pd.read_sql_query(q_select_cell, engine)

    experiment_id = df_record["experiment_id"][0]
    q_select_experiment = "SELECT * FROM Experiment WHERE id = %d" % experiment_id
    df_experiment = pd.read_sql_query(q_select_experiment, engine)

    mouse_id = df_experiment["mouse_id"][0]
    q_select_mouse = "SELECT * FROM Mouse WHERE id = %d" % mouse_id
    df_mouse = pd.read_sql_query(q_select_mouse, engine)

    tool_id = df_record["tool_id"][0]
    q_select_tool = "SELECT * FROM Tool WHERE id = %d" % tool_id
    df_tool = pd.read_sql_query(q_select_tool, engine)

    q_select_map = "SELECT * FROM Map WHERE tool_id = %d" % tool_id
    df_map =  pd.read_sql_query(q_select_map, engine)

    res_dict = {"record": df_record, "cell": df_cell,
                "experiment": df_experiment, "mouse": df_mouse,
                "tool": df_tool, "map": df_map}
    return res_dict