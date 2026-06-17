import os
import sys
import csv
import json
import argparse
import requests


def get_token():
    token = os.environ.get("AIRTABLE_TOKEN")
    if token:
        return token
    saved = os.path.join(os.path.expanduser("~"), ".airtable_token")
    if os.path.exists(saved):
        with open(saved) as f:
            token = f.read().strip()
        if token:
            return token
    token = input("Paste your Airtable token (pat...): ").strip()
    if token:
        with open(saved, "w") as f:
            f.write(token)
        try:
            os.chmod(saved, 0o600)
        except OSError:
            pass
        print("Token saved. It won't ask again next time.")
    return token

TOKEN = get_token()
BASE_ID = "applDN1OeOBgWeB9W"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
API = "https://api.airtable.com/v0"
 
_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(_HERE, "land_data.json")
CSV_FILE = os.path.join(_HERE, "land_data.csv")
 

 
TABLES = {
    "reps":    "REPs",
    "lands":   "Lands",
    "parcels": "Parcels",
    "fields":  "Fields",
    "samples": "Soil Samples",
}
 
LINKS = {
    "rep_to_lands":     "Lands",      
    "land_to_parcels":  "Parcels",       
    "parcel_to_fields": "Fields",         
    "field_to_samples": "Soil Samples",  
    "field_to_tests":   "Soil Tests",    
}
 
NAMES = {
    "rep_name":     "Name",           
    "land_name":    "Land Name",    
    "field_id":     "Field ID",       
    "geojson":      "GeoJSON",        
    "address_full": "Address Full",    
    "village":      "Village/Estate",
    "region":       "Region/County",
}
 
SAMPLE_GROUPS = {
    "sample_info": ["Sample ID", "Test Name", "Layer", "Condition",
                    "Received", "Analysis Date", "Report Date"],
    "coordinate":  ["Coordinate (LatLon)"],
    "ph_acidity":  ["pH H2O", "pH Status", "EC (Salts)",
                    "Exchangeable Acidity", "Acid Saturation"],
    "macronutrients": ["Total Nitrogen (N), %", "Phosphorus (P), ppm",
                       "Potassium (K), ppm", "Calcium (Ca), ppm",
                       "Magnesium (Mg), ppm", "Sulphur (S), ppm", "Sodium"],
    "micronutrients": ["Iron", "Manganese (Mn), ppm", "Boron (B), ppm",
                       "Copper (Cu), ppm", "Zinc (Zn), ppm"],
    "soil_properties": ["CEC, meq/100g", "Organic Matter (OM), %", "C/N ratio"],
    "texture": ["% Sand", "% Silt", "% Clay (Texture Class)", "Heavy Metals"],
}
 
GROUP_LABELS = {
    "sample_info":     "Sample",
    "coordinate":      "Coordinate",
    "ph_acidity":      "pH/Acidity",
    "macronutrients":  "Macronutrient",
    "micronutrients":  "Micronutrient",
    "soil_properties": "Soil Property",
    "texture":         "Texture",
}
 
ALL_RESULT_COLUMNS = [col for cols in SAMPLE_GROUPS.values() for col in cols]
LABELED_HEADERS = [f"{GROUP_LABELS[group]}: {col}"
                   for group, cols in SAMPLE_GROUPS.items() for col in cols]
 

def list_all(table):
    """Download every row of a table; return a lookup: id -> fields."""
    rows, params = [], {}
    while True:
        r = requests.get(f"{API}/{BASE_ID}/{table}", headers=HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
        rows.extend(data["records"])
        if "offset" in data:
            params["offset"] = data["offset"]
        else:
            break
    return {row["id"]: row["fields"] for row in rows}
 
 

def point_from_geojson(geojson_str):
    """Pull one readable 'lat,lon' point out of a GeoJSON polygon."""
    if not geojson_str:
        return None
    try:
        gj = json.loads(geojson_str)
        coords = gj["features"][0]["geometry"]["coordinates"][0][0] 
        lon, lat = coords[0], coords[1]
        return f"{lat},{lon}"
    except (KeyError, IndexError, ValueError, TypeError):
        return None
 
 
def structure_sample(sample):
    """Lay a flat soil sample out into labeled groups, skipping empty fields."""
    structured = {}
    for group_name, columns in SAMPLE_GROUPS.items():
        group = {col: sample[col] for col in columns if col in sample}
        if group:
            structured[group_name] = group
    return structured
 
 
def summarize_sample(s):
    """One-line summary of a structured sample for screen output."""
    info = s.get("sample_info", {})
    ph = s.get("ph_acidity", {})
    macro = s.get("macronutrients", {})
    sid = info.get("Sample ID", "?")
    layer = info.get("Layer", "")
    bits = [f"pH {ph.get('pH H2O', '?')} {ph.get('pH Status', '')}".strip()]
    if "Phosphorus (P), ppm" in macro:
        bits.append(f"P {macro['Phosphorus (P), ppm']}")
    if "Potassium (K), ppm" in macro:
        bits.append(f"K {macro['Potassium (K), ppm']}")
    return f"{sid} ({layer}): " + ", ".join(bits)
 

def build_result():
    print("Downloading tables...")
    reps = list_all(TABLES["reps"])
    lands = list_all(TABLES["lands"])
    parcels = list_all(TABLES["parcels"])
    fields = list_all(TABLES["fields"])
    samples = list_all(TABLES["samples"])
    print(f"Got {len(reps)} reps, {len(lands)} lands, {len(parcels)} parcels, "
          f"{len(fields)} fields, {len(samples)} samples.\n")
 
    def address_of(field):
        parts = [field.get(NAMES["address_full"]), field.get(NAMES["village"]),
                 field.get(NAMES["region"])]
        return ", ".join(p for p in parts if p) or None
 
    def places_for_land(land):
        places = []
        for parcel_id in land.get(LINKS["land_to_parcels"], []):
            parcel = parcels.get(parcel_id, {})
            for field_id in parcel.get(LINKS["parcel_to_fields"], []):
                field = fields.get(field_id, {})
                sample_ids = field.get(LINKS["field_to_samples"], [])
                results = [structure_sample(samples[sid])
                           for sid in sample_ids if sid in samples]
                geojson = field.get(NAMES["geojson"])
                places.append({
                    "field_id": field.get(NAMES["field_id"]),
                    "address": address_of(field),
                    "coordinate_point": point_from_geojson(geojson),  
                    "geojson": geojson,                               
                   
                    "has_soil_test": len(results) > 0,
                   
                    "test_linked_no_results": bool(field.get(LINKS["field_to_tests"])) and not results,
                    "soil_test_results": results,
                })
        return places
 
    result = []
    for rep in reps.values():
        rep_name = rep.get(NAMES["rep_name"], "(no name)")
        rep_lands = []
        for land_id in rep.get(LINKS["rep_to_lands"], []):
            land = lands.get(land_id, {})
            land_name = land.get(NAMES["land_name"])
            if land_name is None and not land.get(LINKS["land_to_parcels"]):
                continue  
            rep_lands.append({
                "land_name": land_name,
                "places": places_for_land(land),
            })
        result.append({"rep": rep_name, "lands": rep_lands})
    return result
 

def write_json(result):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"JSON saved to: {OUTPUT_FILE}")
 
 
def write_csv(result):
    base_cols = ["REP", "Land", "Field ID", "Coordinate", "Address", "Has Soil Test"]
    header = base_cols + LABELED_HEADERS
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for rep in result:
            for land in rep["lands"]:
                for place in land["places"]:
                    row_start = [rep["rep"], land["land_name"], place["field_id"],
                                 place["coordinate_point"], place["address"],
                                 "yes" if place["has_soil_test"] else "no"]
                    if not place["soil_test_results"]:
                        writer.writerow(row_start + [""] * len(ALL_RESULT_COLUMNS))
                        continue
                    for sample in place["soil_test_results"]:
                        flat = {}
                        for group in sample.values():
                            flat.update(group)
                        values = [flat.get(col, "") for col in ALL_RESULT_COLUMNS]
                        writer.writerow(row_start + values)
    print(f"CSV saved to:  {CSV_FILE}")
 
 
def print_place(place, indent="      "):
    print(f"{indent}Place: {place['field_id']}")
    print(f"{indent}  Coordinate: {place['coordinate_point'] or '(none)'}")
    if place["address"]:
        print(f"{indent}  Address: {place['address']}")
    if place["has_soil_test"]:
        n = len(place["soil_test_results"])
        print(f"{indent}  Soil test: YES ({n} sample(s))")
        for s in place["soil_test_results"]:
            print(f"{indent}    - {summarize_sample(s)}")
    elif place["test_linked_no_results"]:
        print(f"{indent}  Soil test: ordered, but no results entered yet")
    else:
        print(f"{indent}  Soil test: none")
 
 
def print_land(land, indent="    "):
    print(f"{indent}Land: {land['land_name'] or '(unnamed)'}")
    if not land["places"]:
        print(f"{indent}  (no places/fields)")
    for place in land["places"]:
        print_place(place, indent + "  ")
 

def cmd_export():
    result = build_result()
    write_json(result)
    write_csv(result)
    print("\nDone.")
 
 
def cmd_rep(name):
    result = build_result()
    needle = name.lower()
    matches = [r for r in result if needle in r["rep"].lower()]
    if not matches:
        print(f"No rep matching {name!r}. Available reps:")
        for r in result:
            print("   -", r["rep"])
        return
    for rep in matches:
        print(f"\nREP: {rep['rep']}")
        if not rep["lands"]:
            print("  (no lands)")
        for land in rep["lands"]:
            print_land(land)
 
 
def cmd_land(name):
    result = build_result()
    needle = name.lower()
    found = False
    for rep in result:
        for land in rep["lands"]:
            if land["land_name"] and needle in land["land_name"].lower():
                found = True
                print(f"\nLand: {land['land_name']}   (REP: {rep['rep']})")
                for place in land["places"]:
                    print_place(place, "    ")
    if not found:
        print(f"No land matching {name!r}.")
 
 
def show_config():
    print("Token set:  ", "yes" if TOKEN else "NO - run: export AIRTABLE_TOKEN=pat...")
    print("Base ID:    ", BASE_ID)
    print("JSON file:  ", OUTPUT_FILE)
    print("CSV file:   ", CSV_FILE)
    print("\nTABLES (table names):")
    for key, name in TABLES.items():
        print(f"   {key:<16} -> {name!r}")
    print("\nLINKS (link fields between tables):")
    for key, name in LINKS.items():
        print(f"   {key:<18} -> {name!r}")
    print("\nNAMES (plain value fields):")
    for key, name in NAMES.items():
        print(f"   {key:<14} -> {name!r}")
    print("\nSAMPLE_GROUPS (how results are grouped):")
    for group, cols in SAMPLE_GROUPS.items():
        print(f"   {group}:")
        for c in cols:
            print(f"        - {c}")
 

def main():
    parser = argparse.ArgumentParser(
        prog="airtable_lands.py",
        description=("Look up land coordinates and soil tests from Airtable.\n"
                     "Workflow: give a rep name -> see their lands + coordinates;\n"
                     "or give a land name -> see its coordinates + soil results."),
        epilog=("Examples:\n"
                "  python3 airtable_lands.py rep \"Justus\"\n"
                "  python3 airtable_lands.py land \"Kaptagat\"\n"
                "  python3 airtable_lands.py export\n"
                "  python3 airtable_lands.py config"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="{rep,land,export,config}")
 
    p_rep = sub.add_parser("rep", help="Look up a REP by name -> lands, coordinates, soil tests")
    p_rep.add_argument("name", help="Rep name or part of it, e.g. \"Justus\"")
 
    p_land = sub.add_parser("land", help="Look up a land by name -> coordinates + soil results")
    p_land.add_argument("name", help="Land name or part of it, e.g. \"Kaptagat\"")
 
    sub.add_parser("export", help="Dump everything to JSON + CSV files")
    sub.add_parser("config", help="Show which Airtable tables/fields the script uses")
 
    args = parser.parse_args()
 
    if args.command == "config":
        show_config()
        return
 
    if not TOKEN:
        print("No token set. Run:  export AIRTABLE_TOKEN=pat...")
        sys.exit(1)
 
    if args.command == "rep":
        cmd_rep(args.name)
    elif args.command == "land":
        cmd_land(args.name)
    elif args.command == "export":
        cmd_export()
 
 
if __name__ == "__main__":
    main()



#1  python3 airtable_lands.py rep "Justus"        (pull a rep by name (change the name)) 

        #python3 airtable_lands.py rep "Justus"
        #python3 airtable_lands.py rep "Helen"
        #python3 airtable_lands.py rep "DFK"
        #python3 airtable_lands.py rep "Becky"


#2   python3 airtable_lands.py land "Kaptagat"     (land)            
#3   python3 airtable_lands.py export           (JSON + CSV)
#4   python3 airtable_lands.py config              (field map)
#5   python3 airtable_lands.py --help              (helpppppp)