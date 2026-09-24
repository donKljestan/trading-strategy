import pandas as pd
import os

def split_csv_by_year(input_file, output_directory):
    """
    Split a .csv file into separate per-year files based on the 'OpenTime' column.

    Parameters:
        input_file (str): Path to the input .csv file.
        output_directory (str): Directory where the output files are saved.
    """
    file_name_without_extension = os.path.splitext(input_file)[0]
    try:
        data = pd.read_csv(input_file)
    except FileNotFoundError:
        print(f"File '{input_file}' not found.")
        return
    except Exception as e:
        print(f"Error loading file: {e}")
        return

    if 'OpenTime' not in data.columns:
        print("Column 'OpenTime' does not exist in the file.")
        return

    try:
        data['OpenTime'] = pd.to_datetime(data['OpenTime'])
    except Exception as e:
        print(f"Error parsing 'OpenTime' column: {e}")
        return

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    data['Year'] = data['OpenTime'].dt.year
    years = data['Year'].unique()

    for year in years:
        yearly_data = data[data['Year'] == year]
        output_file = os.path.join(output_directory, f"{file_name_without_extension}_{year}.csv")
        yearly_data = yearly_data.drop(columns=['Year'])
        yearly_data.to_csv(output_file, index=False)


if __name__ == "__main__":
    symbol = "BTCUSDT"
    input_file = os.path.join(os.getcwd(), "prices", symbol, symbol + "_15minutni.csv")
    output_directory = os.path.join(os.getcwd(), "prices", symbol)
    split_csv_by_year(input_file, output_directory)
