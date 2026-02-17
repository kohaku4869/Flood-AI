import pandas as pd

async def get_camera_status_by_name(str: name):
    df = pd.read_csv("dataset/dataset_camera_day_du2.csv")
    