import pytz, csv

from datetime import datetime
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, redirect, request, url_for, jsonify, send_from_directory, make_response
from io import StringIO, BytesIO
from zipfile import ZipFile
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

from kidzyway.entities import Client, ClientEvent


app = Flask(__name__)
auth = HTTPBasicAuth()
users = {
    "admin": generate_password_hash("K!dzyW@y")
}


@auth.verify_password
def verify_password(username, password):
    if username in users and \
            check_password_hash(users.get(username), password):
        return username


@app.add_template_global
def format_spare_time(x):
    if x is None:
        return ""
    
    spare_time = int(x)
    sign = "-" if spare_time < 0 else ""
    spare_time = abs(spare_time)
    return f"{sign}{int(spare_time/60):02d}:{spare_time%60:02d}"


def _spare_time_ftm(x):
    spare_time_in_minutes = int(x)
    sign = "-" if x < 0 else ""
    spare_time_in_minutes = abs(spare_time_in_minutes)
    spare_time_hours = int(spare_time_in_minutes / 60)
    spare_time_minutes = spare_time_in_minutes % 60

    if spare_time_hours == 0:
        return f"{sign}{spare_time_minutes} minutes"
    elif spare_time_minutes == 0:
        return f"{sign}{spare_time_hours} hours"
    else:
        return f"{sign}{spare_time_hours} hours and {spare_time_minutes} minutes"


@app.add_template_global
def spare_time_ftm(x):
    if x is None:
        return ""
    return _spare_time_ftm(x)


@app.route("/")
@auth.login_required
def main():
    clients_in_instances = ClientEvent.collection.filter(finalized = False).fetch()
    clients_in = []
    for event in clients_in_instances:
        clients_in.append(event.to_dict())
        clients_in[-1]["event_timestamp"] = clients_in[-1]["event_timestamp_utc"].astimezone(pytz.timezone('Asia/Singapore'))
        clients_in[-1]["event_timestamp"] = clients_in[-1]["event_timestamp"].replace(second=0, microsecond=0)

        client = Client.collection.get(event.client_id)
        clients_in[-1]["client"] = client.to_dict()

    pytz.timezone('Asia/Singapore')
    all_clients = Client.collection.order("name").filter(status="active").fetch()

    return render_template("clients.html", clients_in=clients_in, all_clients=all_clients)


@app.route("/newClient", methods=["POST"])
@auth.login_required
def new_client():
    full_name = request.form.get('fullName')
    parent_name = request.form.get('parentName')
    parent_contact = request.form.get('parentContact')
    comments = request.form.get('comments')
    spare_time_minutes = parse_spare_time(request.form.get('spareTime'))
    issue_date = datetime.utcnow()
    valid_till = issue_date + relativedelta(months=6)

    client = Client(
        name=full_name,
        status="active",
        parent_name=parent_name,
        parent_contact=parent_contact,
        spare_time_minutes=spare_time_minutes,
        issue_date=issue_date,
        valid_till=valid_till,
        comments=comments
    )
    client.save()
        
    event = ClientEvent(
        client_id=client.id,
        event="package",
        event_timestamp_utc=datetime.utcnow(),
        finalized=True,
        event_spare_time_minutes=spare_time_minutes
    )
    event.save()

    return redirect(url_for("main"))


@app.route("/deleteClient", methods=["GET"])
@auth.login_required
def delete_client():
    cid = request.args.get('id')
    client = Client.collection.get(cid)
    client.status = "dead"
    client.save()
    return redirect(url_for("main"))


def parse_spare_time(x):
    spare_time_parts = x.split(":")
    if len(spare_time_parts) == 2:
        spare_time_hours = int(spare_time_parts[0])
        spare_time_minutes = int(spare_time_parts[1])
        spare_time = spare_time_hours * 60
        spare_time += spare_time_minutes if spare_time_hours > 0 else -spare_time_minutes
    else:
        spare_time = int(spare_time_parts[0]) * 60
    
    return spare_time


@app.route("/checkin", methods=["GET"])
@auth.login_required
def checkin_client():
    cid = request.args.get('id')
    client = Client.collection.get(cid)
    event = ClientEvent(
        client_id=client.id,
        event="enter",
        event_timestamp_utc=datetime.utcnow(),
        event_spare_time_minutes=client.spare_time_minutes,
        finalized=False
    )
    event.save()
    return redirect(url_for("main"))


@app.route("/checkoutInfo", methods=["GET"])
@auth.login_required
def checkout_info():
    eid = request.args.get('eid')
    enter_event = ClientEvent.collection.get(eid).to_dict()
    enter_event["enter_timestamp"] = enter_event["event_timestamp_utc"].astimezone(pytz.timezone('Asia/Singapore'))
    enter_event["exit_timestamp"] = datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(pytz.timezone('Asia/Singapore'))

    client = Client.collection.get(enter_event["client_id"]).to_dict()
    enter_event["orig_spare_time_minutes"] = client["spare_time_minutes"]

    if enter_event["event"] != "enter":
        return "client did not check in", 500
    
    visit_time_minutes = int((enter_event["exit_timestamp"] - enter_event["enter_timestamp"]).total_seconds() / 60)
    visit_time_fmt = _spare_time_ftm(visit_time_minutes)
    return jsonify(
        dict(
            enter_time=enter_event["enter_timestamp"].strftime("%H:%M:%S"), 
            exit_time=enter_event["exit_timestamp"].strftime("%H:%M:%S"),
            visit_time_fmt=visit_time_fmt,
            visit_time_minutes=visit_time_minutes,
            orig_spare_time_minutes=enter_event["orig_spare_time_minutes"],
            client_id=enter_event["client_id"],
            event_id=enter_event["id"],
            comments=enter_event["comments"]
        )
    )


@app.route("/checkout", methods=["POST"])
@auth.login_required
def checkout_client():
    cid = request.form.get('clientId')
    eid = request.form.get('eventId')
    spare_time = parse_spare_time(request.form.get('spareTime'))
    orig_time = int(request.form.get('origSpareTime'))
    comments = request.form.get('comments')

    ClientEvent(
        client_id = cid,
        event = "leave",
        event_timestamp_utc = datetime.utcnow(),
        finalized = True,
        comments = comments,
        event_spare_time_minutes = orig_time - spare_time
    ).save()

    enter_event = ClientEvent.collection.get(eid)
    enter_event.finalized = True
    enter_event.save()

    client = Client.collection.get(cid)
    client.spare_time_minutes = spare_time
    client.save()

    return redirect(url_for("main"))


@app.route("/updateClientComments", methods=["POST"])
@auth.login_required
def update_client_comments():
    cid = request.form.get('clientId')
    comments = request.form.get("updateComments")

    client = Client.collection.get(cid)
    client.comments = comments
    client.save()

    return redirect(url_for("main"))    


@app.route("/addTime", methods=["POST"])
@auth.login_required
def add_time():
    cid = request.form.get('clientId')
    add_spare_time_miutes = parse_spare_time(request.form.get('addSpareTime'))
    valid_till = datetime.combine(datetime.utcnow().date() + relativedelta(months=6), datetime.min.time())

    client = Client.collection.get(cid)
    client.spare_time_minutes += add_spare_time_miutes
    client.valid_till = valid_till
    client.save()

    ClientEvent(
        client_id = client.id,
        event = "package",
        event_timestamp_utc = datetime.utcnow(),
        finalized = True,
        event_spare_time_minutes = add_spare_time_miutes
    ).save()

    return redirect(url_for("main"))


@app.route("/info", methods=["GET"])
@auth.login_required
def info():
    cid = request.args.get('id')

    client = Client.collection.get(cid).to_dict()
    client["issue_date"] = client["issue_date"].date()
    client["valid_till"] = client["valid_till"].date()

    history = ClientEvent.collection.order("event_timestamp_utc").filter(client_id=client["id"]).fetch()

    history_dics = []
    for event in history:
        history_dics.append(event.to_dict())
        history_dics[-1]["event_timestamp"] = history_dics[-1]["event_timestamp_utc"].astimezone(pytz.timezone('Asia/Singapore'))
        history_dics[-1]["date"] = history_dics[-1]["event_timestamp"].strftime("%m/%d/%Y")
        history_dics[-1]["time"] = history_dics[-1]["event_timestamp"].strftime("%H:%M:%S")
    
    return render_template("info.html", client=client, history=history_dics)


@app.route("/deleteEvent", methods=["GET"])
@auth.login_required
def delete_event():
    eid = request.args.get('id')
    event = ClientEvent.collection.get(eid)
    event.comments = "deleted" if (event.comments is None) else f"{event.comments}, deleted"
    event.finalized = True
    event.save()
    return redirect(url_for("main"))


@app.route("/editVisitComment", methods=["POST"])
@auth.login_required
def edit_visit_comment():
    eid = request.form.get('eid')
    comment = request.form.get('comment')

    event = ClientEvent.collection.get(eid)
    event.comments = comment
    event.save()

    return redirect(url_for("main"))

@app.route("/logo")
@auth.login_required
def logo():
    return send_from_directory("static", "logo.png")

@app.route("/icon/<name>")
@auth.login_required
def icon(name):
    return send_from_directory("static/icon", name)


@app.route("/download_backup")
@auth.login_required
def download_backup():
    clients = list(Client.select().dicts())
    client_events = list(ClientEvent.select().dicts())

    def get_csv(records):
        output = StringIO()
        if len(records) == 0:
            return output
        writer = csv.DictWriter(output, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
        return output

    zip_output = BytesIO()
    with ZipFile(zip_output, 'w') as zipf:
        zipf.writestr('clients.csv', get_csv(clients).getvalue())
        zipf.writestr('events.csv', get_csv(client_events).getvalue())

    response = make_response(zip_output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=backup.zip'
    response.headers['Content-type'] = 'application/zip'
    return response