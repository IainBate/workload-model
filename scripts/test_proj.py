import sys
sys.path.insert(0, '/Users/iain/Workload Model/scripts')
from data_loader import _load_project_load
data = _load_project_load()
print('Total entries:', len(data))
print('Christopher Crispin-Bailey in data:', 'Christopher Crispin-Bailey' in data)
for k in sorted(data.keys()):
    if 'crispin' in k.lower() or 'bailey' in k.lower():
        print(f'  {k}: project_load_raw={data[k].get("project_load_raw", "N/A")}')
