import xml.etree.ElementTree as ET
import os

def get_sheet_data(path, sheet_index):
    # Path is relative to current dir (where temp_excel folder is)
    file_path = f"temp_excel/xl/worksheets/sheet{sheet_index}.xml"
    if not os.path.exists(file_path):
        return f"Sheet {sheet_index} not found"
    
    tree = ET.parse(file_path)
    root = tree.getroot()
    # The namespace is usually {http://schemas.openxmlformats.org/spreadsheetml/2006/main}
    ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    
    rows = []
    for row in root.findall('ns:row', ns):
        row_data = []
        for c in row.findall('ns:c'):
            v = c.find('ns:v')
            row_data.append(v.text if v is not None else "")
        rows.append(row_data)
    return rows

# List of interesting sheets to check for "Teaching", "Research", "Assessment" info
sheets_to_check = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]

for i in sheets_to_check:
    data = get_sheet_data("temp_excel", i)
    if isinstance(data, str):
        print(data)
    else:
        # Print a few rows to see structure
        print(f"--- Sheet {i} ---")
        for row in data[:10]: # Show first 10 rows
            print(row)
        print("-" * 20)

