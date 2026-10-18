import json, sys
sys.path.insert(0, r"C:\Users\ekenh\AppData\Local\Temp\claude\C--Users-ekenh-atlas\95de981c-4a8d-474e-9c3e-450104009d6f\scratchpad\controls")
from sec import *

t = fetch_json("https://www.sec.gov/files/company_tickers.json")
for v in t.values():
    if v["ticker"] in ("SNDK", "IREN", "ETOR", "SNAP", "POET"):
        print(v)
cases = {"sandisk": None, "iren": "0001878848", "etoro": "0001493318", "snap": "0001564408", "poet-technologies": "0001437424"}
for v in t.values():
    if v["ticker"] == "SNDK":
        cases["sandisk"] = cik10(v["cik_str"])
for k, c in cases.items():
    s = fetch_json("https://data.sec.gov/submissions/CIK%s.json" % c)
    print(k, c, s["name"], s["sic"], s["sicDescription"], s.get("tickers"), s.get("exchanges"))
print(COUNTS)
d = fetch("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=3572&owner=include&count=100&start=0")
open(os.path.join(BASE, "browse_sample.html"), "wb").write(d)
print(len(d))
