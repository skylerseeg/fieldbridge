"""
Seed list of 120 heavy civil contractors across the US —
VANCON Technologies' initial FieldBridge sales target universe.

Curated by geography (SE, SW, Midwest, NE, NW) and company profile.
All are known or likely Vista/Viewpoint users based on company size,
type of work, and industry signals.

Run: python -m fieldbridge.saas.prospect_intelligence.seed
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("fieldbridge.seed_prospects")

# fmt: off
PROSPECTS: list[dict] = [
    # ─── SOUTHEAST ───────────────────────────────────────────────────────────
    {"company_name": "Boise Cascade EWP", "website": "targac.com", "state": "AL", "city": "Birmingham", "notes": "earthwork, utilities"},
    {"company_name": "Dunn Construction Company", "website": "dunnconstruction.com", "state": "AL", "city": "Birmingham", "notes": "highways, bridges, earthwork"},
    {"company_name": "Vulcan Materials Company", "website": "vulcanmaterials.com", "state": "AL", "city": "Birmingham", "notes": "aggregates, heavy civil"},
    {"company_name": "Hubbard Group", "website": "hubbardgroup.com", "state": "AL", "city": "Phenix City", "notes": "paving, earthwork"},
    {"company_name": "Brasfield & Gorrie", "website": "brasfieldgorrie.com", "state": "AL", "city": "Birmingham", "notes": "heavy civil, infrastructure"},
    {"company_name": "Rogers Group Inc", "website": "rogersgroupinc.com", "state": "TN", "city": "Nashville", "notes": "aggregates, paving, earthwork"},
    {"company_name": "Dement Construction", "website": "dementconstruction.com", "state": "TN", "city": "Memphis", "notes": "site development, utilities"},
    {"company_name": "Blalock Companies", "website": "blalockcompanies.com", "state": "GA", "city": "Gainesville", "notes": "utilities, water/wastewater"},
    {"company_name": "C.W. Matthews Contracting", "website": "cwmatthews.com", "state": "GA", "city": "Marietta", "notes": "highways, paving, earthwork"},
    {"company_name": "Reeves Construction Company", "website": "reevescc.com", "state": "GA", "city": "Atlanta", "notes": "heavy civil, DOT work"},
    {"company_name": "SAIA Inc", "website": "saiaincorp.com", "state": "GA", "city": "Atlanta", "notes": "utilities, site work"},
    {"company_name": "Ajax Paving Industries of Florida", "website": "ajaxpaving.com", "state": "FL", "city": "Tampa", "notes": "paving, road construction"},
    {"company_name": "Hubbard Construction", "website": "hubbardconstruction.com", "state": "FL", "city": "Winter Park", "notes": "highways, paving, bridges"},
    {"company_name": "Jones Edmunds", "website": "jonesedmunds.com", "state": "FL", "city": "Gainesville", "notes": "water, wastewater, civil"},
    {"company_name": "S&B USA Construction", "website": "sbusaconstruction.com", "state": "FL", "city": "Jacksonville", "notes": "earthwork, utilities"},
    {"company_name": "APAC-Southeast Inc", "website": "apac-southeast.com", "state": "SC", "city": "Columbia", "notes": "paving, aggregates, DOT"},
    {"company_name": "Branch Civil Inc", "website": "branchcivil.com", "state": "VA", "city": "Petersburg", "notes": "earthwork, utilities, bridges"},
    {"company_name": "Allan Myers", "website": "allanmyers.com", "state": "VA", "city": "Worcester", "notes": "highways, heavy civil"},
    {"company_name": "Corman Companies", "website": "corman.net", "state": "VA", "city": "Chantilly", "notes": "heavy civil, rail, marine"},
    {"company_name": "Vecellio & Grogan", "website": "vecellioandgrogan.com", "state": "WV", "city": "Beckley", "notes": "highways, bridges"},
    {"company_name": "Triad Engineering & Contracting", "website": "triadec.com", "state": "NC", "city": "Burlington", "notes": "utilities, water"},
    {"company_name": "S.T. Wooten Corporation", "website": "stwooten.com", "state": "NC", "city": "Wilson", "notes": "paving, earthwork, utilities"},
    {"company_name": "Crowder Construction", "website": "crowderconstructionco.com", "state": "NC", "city": "Charlotte", "notes": "utilities, water/wastewater"},

    # ─── SOUTHWEST / TEXAS ───────────────────────────────────────────────────
    {"company_name": "Sterling Construction", "website": "sterlingconstruction.com", "state": "TX", "city": "Houston", "notes": "highways, heavy civil, bridges"},
    {"company_name": "Balfour Beatty US", "website": "balfourbeattyus.com", "state": "TX", "city": "Dallas", "notes": "heavy civil infrastructure"},
    {"company_name": "SEMA Construction Inc", "website": "semaconstruction.com", "state": "TX", "city": "San Antonio", "notes": "earthwork, site development"},
    {"company_name": "Zachry Construction", "website": "zachrycorp.com", "state": "TX", "city": "San Antonio", "notes": "heavy industrial, civil"},
    {"company_name": "Martin Marietta Materials", "website": "martinmarietta.com", "state": "TX", "city": "Raleigh", "notes": "aggregates, paving"},
    {"company_name": "APAC Texas Inc", "website": "apactexas.com", "state": "TX", "city": "Dallas", "notes": "paving, highways"},
    {"company_name": "Reynolds Inc", "website": "reynoldsinc.com", "state": "TX", "city": "Houston", "notes": "utilities, earthwork"},
    {"company_name": "Jerry Pate Company", "website": "jerrypate.com", "state": "AL", "city": "Pensacola", "notes": "site development, utilities"},
    {"company_name": "JLB Contracting", "website": "jlbcontracting.com", "state": "TX", "city": "Fort Worth", "notes": "earthwork, site development"},
    {"company_name": "RoadSafe Traffic Systems", "website": "roadsafetraffic.com", "state": "TX", "city": "Houston", "notes": "traffic control, highways"},
    {"company_name": "Baker Construction", "website": "bakerconstruction.com", "state": "TX", "city": "Houston", "notes": "concrete, industrial"},
    {"company_name": "HNTB Corporation", "website": "hntb.com", "state": "MO", "city": "Kansas City", "notes": "transportation, bridges"},
    {"company_name": "Oldcastle Infrastructure", "website": "oldcastleinfrastructure.com", "state": "GA", "city": "Atlanta", "notes": "precast, utilities"},
    {"company_name": "Southwest Asphalt Paving", "website": "swapc.net", "state": "AZ", "city": "Phoenix", "notes": "paving, highways"},
    {"company_name": "Granite Construction", "website": "graniteconstruction.com", "state": "CA", "city": "Watsonville", "notes": "heavy civil, highways, earthwork"},
    {"company_name": "CORE Construction", "website": "corecon.com", "state": "AZ", "city": "Chandler", "notes": "heavy civil, site development"},
    {"company_name": "Arizona Paving and Grading", "website": "azpaving.com", "state": "AZ", "city": "Chandler", "notes": "paving, earthwork"},

    # ─── MIDWEST ─────────────────────────────────────────────────────────────
    {"company_name": "Walsh Construction", "website": "walshgroup.com", "state": "IL", "city": "Chicago", "notes": "heavy civil, bridges, transit"},
    {"company_name": "Kiewit Corporation", "website": "kiewit.com", "state": "NE", "city": "Omaha", "notes": "heavy civil, mining, oil & gas"},
    {"company_name": "Michels Corp", "website": "michels.us", "state": "WI", "city": "Brownsville", "notes": "utilities, pipelines, power"},
    {"company_name": "Rieth-Riley Construction", "website": "riethrileyconstruction.com", "state": "IN", "city": "Goshen", "notes": "paving, earthwork, DOT"},
    {"company_name": "Milestone Contractors", "website": "milestonecontractors.com", "state": "IN", "city": "Indianapolis", "notes": "highways, paving, bridges"},
    {"company_name": "E&B Paving", "website": "ebpaving.com", "state": "IN", "city": "Anderson", "notes": "paving, site development"},
    {"company_name": "Gerhart-Cavanaugh International", "website": "gerhartcavanaugh.com", "state": "OH", "city": "Columbus", "notes": "earthwork, utilities"},
    {"company_name": "Kokosing Construction", "website": "kokosing.com", "state": "OH", "city": "Fredericktown", "notes": "heavy civil, highways, bridges"},
    {"company_name": "Shelly & Sands Inc", "website": "shellyandsands.com", "state": "OH", "city": "Zanesville", "notes": "earthwork, paving, bridges"},
    {"company_name": "The Ruhlin Company", "website": "ruhlin.com", "state": "OH", "city": "Sharon Center", "notes": "heavy civil, bridges, marine"},
    {"company_name": "Trowbridge & Wolf", "website": "trowbridgewolf.com", "state": "OH", "city": "Ithaca", "notes": "water, wastewater"},
    {"company_name": "Hardrives Inc", "website": "hardrives.com", "state": "MN", "city": "Rogers", "notes": "paving, earthwork, highways"},
    {"company_name": "Ames Construction", "website": "amesconstruction.com", "state": "MN", "city": "Burnsville", "notes": "heavy civil, highways, rail"},
    {"company_name": "C.S. McCrossan", "website": "csmccrossan.com", "state": "MN", "city": "Maple Grove", "notes": "paving, earthwork, bridges"},
    {"company_name": "Knife River Corporation", "website": "kniferiver.com", "state": "MN", "city": "Bismarck", "notes": "aggregates, paving, earthwork"},
    {"company_name": "W. Lee Massey Construction", "website": "masseyconstruction.com", "state": "MN", "city": "Rosemount", "notes": "utilities, water"},
    {"company_name": "Fagen Inc", "website": "fageninc.com", "state": "MN", "city": "Granite Falls", "notes": "industrial, heavy civil"},
    {"company_name": "Diamond Surface Inc", "website": "diamondsurfaceinc.com", "state": "MN", "city": "New Brighton", "notes": "concrete, paving"},
    {"company_name": "Veit & Company Inc", "website": "veitusa.com", "state": "MN", "city": "Rogers", "notes": "earthwork, demolition, utilities"},
    {"company_name": "R.H. Sheppard Co", "website": "rhsheppard.com", "state": "PA", "city": "Hanover", "notes": "earthwork, site development"},
    {"company_name": "Ryan Companies US", "website": "ryancompanies.com", "state": "MN", "city": "Minneapolis", "notes": "heavy civil development"},
    {"company_name": "Boldt Company", "website": "boldt.com", "state": "WI", "city": "Appleton", "notes": "heavy industrial, civil"},
    {"company_name": "IMCO General Construction", "website": "imcogeneral.com", "state": "WI", "city": "Wausau", "notes": "earthwork, utilities"},

    # ─── MOUNTAIN / NORTHWEST ────────────────────────────────────────────────
    {"company_name": "Stacy and Witbeck Inc", "website": "stacyandwitbeck.com", "state": "CA", "city": "Oakland", "notes": "rail, transit, heavy civil"},
    {"company_name": "Teichert Construction", "website": "teichert.com", "state": "CA", "city": "Sacramento", "notes": "aggregates, paving, earthwork"},
    {"company_name": "RMC Pacific Materials", "website": "rmcpacific.com", "state": "CA", "city": "Pleasanton", "notes": "aggregates, concrete"},
    {"company_name": "McAninch Corp", "website": "mcaninch.com", "state": "IA", "city": "Des Moines", "notes": "earthwork, utilities, paving"},
    {"company_name": "Elford Inc", "website": "elford.com", "state": "OH", "city": "Columbus", "notes": "heavy civil, bridges"},
    {"company_name": "Cemrock Concrete & Construction", "website": "cemrock.com", "state": "OR", "city": "Portland", "notes": "concrete, earthwork"},
    {"company_name": "Anderson Perry & Associates", "website": "andersonperry.com", "state": "OR", "city": "Pendleton", "notes": "civil, utilities, water"},
    {"company_name": "Max J. Kuney Company", "website": "kuney.com", "state": "WA", "city": "Spokane", "notes": "heavy civil, earthwork, bridges"},
    {"company_name": "Mortenson Construction", "website": "mortenson.com", "state": "MN", "city": "Minneapolis", "notes": "heavy industrial, wind, civil"},
    {"company_name": "Hensel Phelps", "website": "henselphelps.com", "state": "CO", "city": "Greeley", "notes": "heavy civil, federal"},
    {"company_name": "GE Johnson Construction", "website": "gejohnson.com", "state": "CO", "city": "Colorado Springs", "notes": "heavy civil"},
    {"company_name": "Saunders Construction", "website": "saundersinc.com", "state": "CO", "city": "Centennial", "notes": "heavy civil, site development"},
    {"company_name": "United Companies", "website": "unitedcompanies.com", "state": "CO", "city": "Denver", "notes": "paving, aggregates"},
    {"company_name": "S&L Industrial", "website": "slindustrial.net", "state": "UT", "city": "Salt Lake City", "notes": "industrial, utilities"},
    {"company_name": "Geneva Rock Products", "website": "genevarock.com", "state": "UT", "city": "Orem", "notes": "aggregates, paving, earthwork"},
    {"company_name": "Wadsworth Brothers Construction", "website": "wadsworthbrothers.com", "state": "UT", "city": "Draper", "notes": "highways, bridges, earthwork"},
    {"company_name": "Staker Parson Companies", "website": "stakerparson.com", "state": "UT", "city": "Ogden", "notes": "aggregates, paving, ready-mix"},

    # ─── NORTHEAST ───────────────────────────────────────────────────────────
    {"company_name": "Northeast Remsco Construction", "website": "nrci.com", "state": "NJ", "city": "South Bound Brook", "notes": "heavy civil, transit, rail"},
    {"company_name": "Interstate Industrial Corp", "website": "interstateind.com", "state": "NY", "city": "Maspeth", "notes": "utilities, earthwork"},
    {"company_name": "Tully Construction", "website": "tullyconstruction.com", "state": "NY", "city": "Flushing", "notes": "earthwork, utilities, marine"},
    {"company_name": "Five Star Electric", "website": "fivestarelectric.com", "state": "NY", "city": "Flushing", "notes": "electrical, transit"},
    {"company_name": "LaRosa Building Group", "website": "larosabuilding.com", "state": "NY", "city": "Elmsford", "notes": "site development"},
    {"company_name": "Posillico Inc", "website": "posillico.com", "state": "NY", "city": "Farmingdale", "notes": "earthwork, utilities, marine"},
    {"company_name": "Garden State Highway Products", "website": "gshp.com", "state": "NJ", "city": "Millville", "notes": "highways, concrete"},
    {"company_name": "J. Fletcher Creamer & Son", "website": "jfletcher.com", "state": "NJ", "city": "Hackensack", "notes": "utilities, water, earthwork"},
    {"company_name": "Trumbull-Nelson Construction", "website": "trumbullnelson.com", "state": "NH", "city": "Hanover", "notes": "heavy civil, utilities"},
    {"company_name": "DW White Construction", "website": "dwwhite.com", "state": "MA", "city": "Plainville", "notes": "highways, utilities"},
    {"company_name": "P.J. Keating Company", "website": "pjkeating.com", "state": "MA", "city": "Lunenburg", "notes": "aggregates, paving"},
    {"company_name": "E.T. & L. Corp", "website": "etlcorp.com", "state": "CT", "city": "Trumbull", "notes": "earthwork, utilities"},
    {"company_name": "O&G Industries", "website": "ogindustries.com", "state": "CT", "city": "Torrington", "notes": "aggregates, paving, earthwork"},
    {"company_name": "R.J. Grondin & Sons", "website": "grondinandsonsinc.com", "state": "ME", "city": "Gorham", "notes": "earthwork, utilities, paving"},
    {"company_name": "Lane Construction", "website": "laneconstruction.com", "state": "CT", "city": "Shelton", "notes": "highways, tunnels, heavy civil"},
    {"company_name": "Cianbro Corporation", "website": "cianbro.com", "state": "ME", "city": "Pittsfield", "notes": "heavy civil, bridges, industrial"},
    {"company_name": "Pike Industries", "website": "pikeindustries.com", "state": "NH", "city": "Belmont", "notes": "paving, aggregates, earthwork"},

    # ─── MID-ATLANTIC / GREAT LAKES ──────────────────────────────────────────
    {"company_name": "Waypoint Environmental Consultants", "website": "waypointenviro.com", "state": "PA", "city": "Kennett Square", "notes": "utilities, environmental"},
    {"company_name": "Glenn O. Hawbaker Inc", "website": "goh-inc.com", "state": "PA", "city": "State College", "notes": "paving, aggregates, earthwork"},
    {"company_name": "Trumbull Corporation", "website": "trumbullcorp.com", "state": "PA", "city": "Pittsburgh", "notes": "heavy civil, bridges, marine"},
    {"company_name": "Plenary Group", "website": "plenarygroup.com", "state": "PA", "city": "Philadelphia", "notes": "heavy civil, P3"},
    {"company_name": "Wohlsen Construction", "website": "wohlsen.com", "state": "PA", "city": "Lancaster", "notes": "heavy civil, healthcare"},
    {"company_name": "H&K Group Inc", "website": "hkgroupinc.com", "state": "PA", "city": "Skippack", "notes": "aggregates, paving, earthwork"},
    {"company_name": "Pennoni Associates", "website": "pennoni.com", "state": "PA", "city": "Philadelphia", "notes": "civil engineering, utilities"},
    {"company_name": "Greenman-Pedersen Inc", "website": "gpinet.com", "state": "PA", "city": "Blue Bell", "notes": "bridges, highways"},
    {"company_name": "Meco-Henne Contracting", "website": "mecohenne.com", "state": "MD", "city": "Millington", "notes": "utilities, earthwork"},
    {"company_name": "Facchina Construction", "website": "facchina.com", "state": "MD", "city": "La Plata", "notes": "heavy civil, marine"},
    {"company_name": "Shirley Contracting Company", "website": "shirleycontracting.com", "state": "VA", "city": "Lorton", "notes": "highways, earthwork, bridges"},
    {"company_name": "Superior Industries International", "website": "superior-ind.com", "state": "MN", "city": "Morris", "notes": "aggregates, material handling"},
    {"company_name": "FNF Construction", "website": "fnfconstruction.com", "state": "AZ", "city": "Tempe", "notes": "highways, earthwork, bridges"},
    {"company_name": "APAC-Central", "website": "apac-central.com", "state": "KS", "city": "Wichita", "notes": "paving, highways, DOT"},
    {"company_name": "Emery Sapp & Sons", "website": "ess.com", "state": "MO", "city": "Columbia", "notes": "earthwork, utilities, site dev"},
    {"company_name": "CECO Concrete Construction", "website": "cecoconcrete.com", "state": "MO", "city": "Kansas City", "notes": "concrete, heavy civil"},
    {"company_name": "KBS Construction", "website": "kbsconstruct.com", "state": "KY", "city": "Lexington", "notes": "site development, utilities"},
    {"company_name": "Superior Construction", "website": "superiorconstruction.com", "state": "IN", "city": "Gary", "notes": "heavy civil, highways, bridges"},
    {"company_name": "Civil & Environmental Consultants", "website": "cecinc.com", "state": "PA", "city": "Pittsburgh", "notes": "environmental, utilities"},
    {"company_name": "Dore & Associates Contracting", "website": "doreandassoc.com", "state": "MI", "city": "Bay City", "notes": "heavy civil, marine, bridges"},

    # ─── VANCON HOME REGION (SOUTHEAST TARGET DENSITY) ───────────────────────
    {"company_name": "Hardaway Construction", "website": "hardawayconstruction.com", "state": "TN", "city": "Nashville", "notes": "earthwork, utilities, bridges"},
    {"company_name": "Jones Bros Contractors", "website": "jonesbroscontractors.com", "state": "TN", "city": "Mount Juliet", "notes": "earthwork, bridges, highways"},
    {"company_name": "Trevcon Construction", "website": "trevcon.com", "state": "TN", "city": "Gallatin", "notes": "utilities, site development"},
    {"company_name": "Greer Industries", "website": "greer-industries.com", "state": "WV", "city": "Morgantown", "notes": "aggregates, paving, earthwork"},
    {"company_name": "APAC Inc - Tennessee", "website": "apac-tn.com", "state": "TN", "city": "Nashville", "notes": "paving, highways"},
    {"company_name": "Cumberland Plateau Inc", "website": "cumberlandplateau.net", "state": "TN", "city": "Crossville", "notes": "utilities, site development"},
    {"company_name": "Capital City Paving", "website": "capitalcitypaving.com", "state": "TN", "city": "Nashville", "notes": "paving, concrete"},
    {"company_name": "Civil Constructors Inc", "website": "civilconstructors.com", "state": "MI", "city": "Battle Creek", "notes": "heavy civil, utilities"},
    {"company_name": "Barge Design Solutions", "website": "bargedesign.com", "state": "TN", "city": "Nashville", "notes": "civil engineering, utilities"},
]
# fmt: on


def get_seed_prospects() -> list[dict]:
    """Return the full seed list for insertion into the prospect DB."""
    return PROSPECTS


def save_seed_json(output_path: str = "prospects_seed.json") -> None:
    """Write seed list to a JSON file (useful for manual review/import)."""
    path = Path(output_path)
    path.write_text(json.dumps(PROSPECTS, indent=2))
    log.info(f"Wrote {len(PROSPECTS)} prospects to {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    save_seed_json()
    print(f"\nTotal prospects: {len(PROSPECTS)}")

    by_state: dict[str, int] = {}
    for p in PROSPECTS:
        s = p["state"]
        by_state[s] = by_state.get(s, 0) + 1

    print("\nBy state:")
    for state, count in sorted(by_state.items(), key=lambda x: -x[1]):
        print(f"  {state}: {count}")
