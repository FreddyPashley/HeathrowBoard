import flask
import requests
import json
import datetime
import random

apikey = "ZMXEEL3SBOYF8B1UB1FDW5RKNNK7AWUR"
airport = "LTFM"

app = flask.Flask(__name__)

flights = {}

with open("airports.json") as f:
    airports_ = json.load(f)
airports = {k: airports_[k] for k in airports_ if k.isalpha()}

def loadData():
    with open("flights.json") as f:
        flights_ = json.load(f)
    for item in flights_:
        if item["type"] == "table" and item["name"] == "flights":
            break
    del flights_
    data = item["data"]
    flights_ = {k["callsign"]: {"callsign": k["callsign"],
                               "flightnum": k["flight_number"],
                               "origin": k["origin_icao"],
                               "destination": k["destination_icao"],
                               "departure_time": k["departure_time"],
                               "arrival_time": k["arrival_time"],
                               "aircraft": k["aircraft_icao"],
                               "gate": [k["terminal"], k["gate"]]} for k in data}
    for cs in flights_:
        if flights_[cs]["departure_time"] is not None:
            flights_[cs]["departure_time"] = ":".join(flights_[cs]["departure_time"].split()[-1].split(":")[:2])
        if flights_[cs]["arrival_time"] is not None:
            flights_[cs]["arrival_time"] = ":".join(flights_[cs]["arrival_time"].split()[-1].split(":")[:2])
    global flights
    flights = flights_.copy()

def sort_time_after_midnight(time_str):
    """
    Convert HH:MM to minutes, with early morning (00:00-05:59) treated as after 23:59
    """
    h, m = map(int, str(time_str).split()[1].split(".")[0].split(":")[:2])
    total_minutes = h * 60 + m
    if total_minutes < 360:  # before 06:00
        total_minutes += 24 * 60
    return total_minutes

def flight_sort_key(flight):
    """
    Sort by day-of-flight (dof) and then by time.
    """
    day, month = flight["dof"]
    time_minutes = sort_time_after_midnight(datetime.datetime.strptime(flight["time"], "%H:%M"))
    return (month, day, time_minutes)

def getFlights():
    try:
        res = requests.get("https://api.ivao.aero/v2/tracker/now/pilots?apikey="+apikey)
    except Exception as err:
        print(err)
        return {}
    res = res.json()
    tracks_ = {}
    session = requests.Session()
    for k in res:
        tracks_[k["callsign"]] = {"callsign": k["callsign"],
                                  "fp": k["flightPlan"]}
        if k["lastTrack"] is not None:
            tracks_[k["callsign"]]["state"] = k["lastTrack"]["state"]
            tracks_[k["callsign"]]["arrD"] = k["lastTrack"]["arrivalDistance"]
            tracks_[k["callsign"]]["speed"] = k["lastTrack"]["groundSpeed"]
        else:
            tracks_[k["callsign"]]["state"] = ""
            tracks_[k["callsign"]]["arrD"] = None
            tracks_[k["callsign"]]["speed"] = None
    tracks = {}
    for k in tracks_:
        item = tracks_[k]
        if "departureId" not in item["fp"] or "arrivalId" not in item["fp"]:
            continue
        if item["fp"]["departureId"] == airport or item["fp"]["arrivalId"] == airport:
            tracks[k] = item
    for k in tracks:
        try:
            fid = tracks[k]["fp"]["id"]
        except Exception as err:
            print(err)
            print(k)
            tracks[k]["depTime"] = "00:00"
            tracks[k]["arrTime"] = "00:00"
            continue
        try:
            res2 = session.get("https://api.ivao.aero/v2/tracker/flightPlans/" + str(fid) + "?apiKey=" + apikey)
        except Exception as err:
            print(err)
            return {}
        res2 = res2.json()
        if "departureTime" not in res2: return {}
        if "DOF/" not in res2["remarks"]:
            dof = [datetime.datetime.now().day, datetime.datetime.now().month]
        else:
            dof = res2["remarks"].split("DOF/")[1].split()[0]
            dof = [int(dof[5:7]), int(dof[3:5])]
        tracks[k]["dof"] = dof
        depT = res2["departureTime"]
        eet = res2["eet"]
        groundEta = depT + eet
        groundEtaH = groundEta // 3600
        groundEtaM = ((groundEta % 3600) // 60)
        while groundEtaH >= 24:
            groundEtaH -= 24
        groundEtaH = str(groundEtaH)
        groundEtaM = str(groundEtaM)
        if len(groundEtaH) == 1: groundEtaH = "0" + groundEtaH
        if len(groundEtaM) == 1: groundEtaM = "0" + groundEtaM
        groundEta = groundEtaH + ":" + groundEtaM
        tracks[k]["groundEta"] = groundEta
        tracks[k]["depTime"] = ":".join([("0" if len(str(i)) == 1 else "") + str(i) for i in [(depT // 3600), ((depT % 3600) // 60)]])
        arrD = tracks[k]["arrD"]
        speed = tracks[k]["speed"]
        if arrD is None or speed is None or int(speed) == 0:
            tracks[k]["eta"] = tracks[k]["depTime"]
            tracks[k]["arr"] = tracks[k]["depTime"]
        else:
            tracks[k]["arr"] = ":".join(str(datetime.datetime.now() + datetime.timedelta(seconds=((arrD / speed) * 3600)) + datetime.timedelta(minutes=random.randint(10, 20))).split(" ")[1].split(".")[0].split(":")[:2])
            tracks[k]["eta"] = ":".join(str(datetime.datetime.now() + datetime.timedelta(seconds=((arrD / speed) * 3600))).split(" ")[1].split(".")[0].split(":")[:2])
    return tracks

def getData():
    heathrow_flights = getFlights()
    departures = {k: heathrow_flights[k] for k in heathrow_flights if heathrow_flights[k]["fp"]["departureId"] == airport}
    arrivals = {k: heathrow_flights[k] for k in heathrow_flights if heathrow_flights[k]["fp"]["arrivalId"] == airport}
    
    to_remove = []

    """
    DEPARTURES:
    up to 30mins before slot: Gate shown XX:XX (white)
    30-16 before slot: Go to Gate (white)
    15-6 before slot: Boarding (green)
    5-off blocks: Flight closing (yellow)
    off blocks: Gate closed (red)
    Airborne: Departed (white)
    Initial climb: Departed (white)
    En Route: [Drop off list]

    Enquire airline
    """

    toadd = {"d": {}, "a": {}}
    for callsign in departures:
        for i in range(10):
            toadd["d"][callsign[:len(callsign)-1]+str(i)] = departures[callsign]

    for callsign in arrivals:
        for i in range(10):
            toadd["a"][callsign[:len(callsign)-1]+str(i)] = arrivals[callsign]

    for k in toadd:
        if k == "d":
            for j in toadd[k]:
                departures[j] = toadd[k][j]
        else:
            for j in toadd[k]:
                arrivals[j] = toadd[k][j]

    for callsign in departures:
        if callsign in flights:
            departures[callsign]["flight_number"] = flights[callsign]["flightnum"]
            if flights[callsign]["departure_time"] == None:
                flights[callsign]["departure_time"] = departures[callsign]["depTime"]
            departures[callsign]["time"] = flights[callsign]["departure_time"]
            departures[callsign]["gate"] = flights[callsign]["gate"]
        else:
            departures[callsign]["flight_number"] = callsign
            departures[callsign]["time"] = departures[callsign]["depTime"]
            departures[callsign]["gate"] = ["", ""]  # Find from API
        if departures[callsign]["fp"]["arrival"]["icao"] in airports:
            departures[callsign]["arrival_airport"] = airports[departures[callsign]["fp"]["arrival"]["icao"]]["name"].replace(".", "").strip()
        else:
            departures[callsign]["arrival_airport"] = departures[callsign]["fp"]["arrival"]["icao"]
        
        if departures[callsign]["state"] == "Boarding":
            if callsign not in flights:
                departures[callsign]["state"] = "Enquire airline"
            else:
                ...
                """
                if timebefore() > 30:
                    departures[callsign]["state"] = "Gate shown " + before30()
                if timebefore() in range(16, 31):
                    departures[callsign]"state"] = "Go to Gate"
                if timebefore() in range(6, 16):
                    departures[callsign]["state"] = "Boarding"
                if timebefore() <= 5:
                    departures[callsign]["state"] = "Flight closing"
            """
            departures[callsign]["colour"] = "white"
        if departures[callsign]["state"] == "Departing":
            departures[callsign]["state"] = "Gate closed"
            departures[callsign]["colour"] = "red"
            departures[callsign]["gate"] = ["", ""]
        if departures[callsign]["state"] in ["Departed", "Initial Climb"]:
            departures[callsign]["state"] = "Departed"
            departures[callsign]["colour"] = "white"
            departures[callsign]["gate"] = ["", ""]
        if departures[callsign]["state"] in ["En Route", "Approach", "Landed", "On Blocks"]:
            # to_remove.append(callsign)
            ...

        if callsign in arrivals:
            to_remove.append(callsign)

    """
    ARRIVALS:
    On ground (dep) / initial climb: Scheduled (white)
    Airborne: Expected XX:XX (white)
    On ground (arr): Landed (white)
    On blocks: Arrived
    On blocks + 5: [Drop off list]
    """

    for callsign in arrivals:
        if callsign in flights:
            arrivals[callsign]["flight_number"] = flights[callsign]["flightnum"]
            if flights[callsign]["arrival_time"] == None:
                flights[callsign]["arrival_time"] = "00:00"
            arrivals[callsign]["time"] = flights[callsign]["arrival_time"]
            arrivals[callsign]["gate"] = flights[callsign]["gate"]
        else:
            arrivals[callsign]["flight_number"] = callsign
            arrivals[callsign]["time"] = arrivals[callsign]["groundEta"]
            arrivals[callsign]["gate"] = ["", ""]  # Find from API
        if arrivals[callsign]["fp"]["departure"]["icao"] in airports:
            arrivals[callsign]["departure_airport"] = airports[arrivals[callsign]["fp"]["departure"]["icao"]]["name"].replace(".", "").strip()
        else:
            arrivals[callsign]["departure_airport"] = arrivals[callsign]["fp"]["departure"]["icao"]
        arrivals[callsign]["gate"] = ["", ""]

        arrivals[callsign]["colour"] = "white"
        if arrivals[callsign]["state"] in ["Boarding", "Departing"]:
            arrivals[callsign]["state"] = "Scheduled"
        if arrivals[callsign]["state"] in ["Initial Climb", "En Route", "Approach"]:
            arrivals[callsign]["state"] = "Expected   " + arrivals[callsign]["eta"]
        if arrivals[callsign]["state"] == "On Blocks":
            arrivals[callsign]["state"] = "Arrived"  # Time???

    for callsign in to_remove:
        while callsign in departures:
            del departures[callsign]
        while callsign in arrivals:
            del arrivals[callsign]

    return {"departures": departures, "arrivals": arrivals}

def layoutData(data):
    per_col = 24

    data["departures"] = sorted(data["departures"].values(), key=flight_sort_key)
    data["arrivals"] = sorted(data["arrivals"].values(), key=flight_sort_key)

    data["dep1"] = data["departures"][:per_col]
    data["dep2"] = data["departures"][per_col:(per_col*2)-1]

    data["arr1"] = data["arrivals"][:per_col-1]
    data["arr2"] = data["arrivals"][per_col-1:(per_col-1)*2]

    return data

@app.route("/")
def index():
    loadData()
    data = getData()
    data = layoutData(data)
    now = datetime.datetime.now()
    timestr = f"{('0' if len(str(now.hour)) == 1 else '') + str(now.hour)}:{('0' if len(str(now.minute)) == 1 else '') + str(now.minute)} | 7 March"
    return flask.render_template("index.html",
                                 data=data,
                                 timenow=timestr)

app.run("0.0.0.0", port=6767)
