import requests
import json
import time
import os

#
#   **** Opsgenie Configuration ****
#
opsgenie_api_url = "https://api.opsgenie.com"
opsgenie_alert_endpoint = "/v2/alerts/"
opsgenie_teams_endpoint = "/v2/teams/"
tinyId_req_params = {'identifierType': 'tiny'}
auth_header = {'Authorization': 'GenieKey ' + os.environ["OG_API_KEY"]}


def lambda_handler(event, context):
    # Makes a GET request to OpsGenie Alert API and returns the alert with given alert id.
    def get_alert(alertTinyId):
        req = requests.get(opsgenie_api_url + opsgenie_alert_endpoint + alertTinyId, params=tinyId_req_params,
                           headers=auth_header)
        alert = req.json()

        return alert["data"]

    def get_alert_tinyid(alertId):
        req = requests.get(opsgenie_api_url + opsgenie_alert_endpoint + alertId, params=None, headers=auth_header)
        alert = req.json()

        return alert["data"]["tinyId"]

    def get_alert_description_and_details(alertTinyId):
        alert = get_alert(alertTinyId)

        description = alert["description"]
        details = alert["details"]

        result = (description, details)

        return result

    # Creates sub-alerts for each team given by "teamsToNotify" in the alert details.
    def create_sub_alerts(alert_description, alert_details):
        alert_to_create = event["alert"]
        alert_to_create["description"] = alert_description
        alert_to_create["details"] = alert_details
        alert_tinyId = event["alert"]["tinyId"]

        teams_list = str(alert_details["teamsToNotify"])

        teams = teams_list.split(',')

        results = []

        for team in teams:
            team = team.strip()

            alert_to_create["teams"] = [{"name": team}]

            if "teamsToNotify" in alert_to_create["details"]:
                del alert_to_create["details"]["teamsToNotify"]

            alert_to_create["alias"] = ""
            alert_to_create["details"]["rootAlertTinyId"] = event["alert"]["tinyId"]
            alert_to_create["user"] = "AWSLambda"  # Set the user as AWSLambda, in order to prevent loop when the
            # the callback of creating alert arrives.

            req = requests.post(opsgenie_api_url + opsgenie_alert_endpoint, json=alert_to_create, params=None,
                                headers=auth_header)
            result = req.json()

            results.append(
                "Create sub-alert result for team [" + team + "]: " + json.dumps(result).decode('string_escape'))
            for i in range(0, 3):
                time.sleep(0.3)
                req_get_sub_alert = requests.get("https://api.opsgenie.com/v2/alerts/requests/" + result["requestId"],
                                                 params=None, headers=auth_header)
                result_of_sub = req_get_sub_alert.json()
                if result_of_sub["data"]["success"]:
                    break

            sub_tinyId = get_alert_tinyid(result_of_sub["data"]["alertId"])
            req_data_add_tag = {
                "tags": ["subAlert:" + sub_tinyId]
            }

            req_add_tag = requests.post(opsgenie_api_url + opsgenie_alert_endpoint + alert_tinyId + "/tags",
                                        json=req_data_add_tag, params=tinyId_req_params, headers=auth_header)
            result_add_tag = req_add_tag.json()
            results.append(
                "Add tags to root alert result for sub-alert: " + json.dumps(result_add_tag).decode('string_escape'))

        return results

    # Adds a note to the root alert when a sub-alert is acknowledged.
    def add_note_to_the_root_alert(alert_details):
        root_alert_tinyId = alert_details["rootAlertTinyId"]

        alert_tinyId = event["alert"]["tinyId"]

        alert_req = get_alert(alert_tinyId)

        team_id_that_acks = alert_req["teams"][0]["id"]

        req_team = requests.get(opsgenie_api_url + opsgenie_teams_endpoint + team_id_that_acks, params=None,
                                headers=auth_header)

        team_that_acks = req_team.json()

        team_name_acks = str(team_that_acks["data"]["name"])

        req_data = {
            "note": "User [" + event["alert"][
                "username"] + "] acknowledged the alert for team [" + team_name_acks + "]."
        }

        req = requests.post(opsgenie_api_url + opsgenie_alert_endpoint + root_alert_tinyId + "/notes",
                            json=req_data, params=tinyId_req_params, headers=auth_header)

        result = req.json()

        return "Result of AddNote to Root Alert: " + str(result)

    # Closes the root and the sub-alerts when either the root alert or one of the sub-alerts is closed.
    def close_root_and_sub_alerts(alert_details):
        results = []

        if "teamsToNotify" in alert_details:
            tags = event["alert"]["tags"]

            for tag in tags:
                if str(tag).startswith("subAlert:"):
                    sub_tinyId = str(tag).replace("subAlert:", "")

                    reqData = {
                        "user": "AWSLambda"
                    }

                    requests.post(opsgenie_api_url + opsgenie_alert_endpoint + sub_tinyId + "/close",
                                  params=tinyId_req_params, json=reqData, headers=auth_header)

        elif "rootAlertTinyId" in alert_details:
            root_alert_tinyId = alert_details["rootAlertTinyId"]
            root_alert = get_alert(root_alert_tinyId)
            tags = root_alert["tags"]

            for tag in tags:
                print(tag)
                if str(tag).startswith("subAlert:"):
                    sub_tinyId = str(tag).replace("subAlert:", "")

                    if sub_tinyId != event["alert"]["tinyId"]:
                        reqData = {
                            "user": "AWSLambda"
                        }

                        requests.post(
                            opsgenie_api_url + opsgenie_alert_endpoint + sub_tinyId + "/close",
                            json=reqData,
                            params=tinyId_req_params,
                            headers=auth_header)

            req_data_close_root_alert = {
                "user": "AWSLambda"
            }
            requests.post(
                opsgenie_api_url + opsgenie_alert_endpoint + root_alert_tinyId + "/close",
                json=req_data_close_root_alert, params=tinyId_req_params, headers=auth_header)
        else:
            results.append("Alert is neither a root alert nor a sub-alert.")

        return results

    # Load API Gateway event "body" as dict
    event = json.loads(event["body"])

    action = event["action"]

    alert_description_and_details_tuple = get_alert_description_and_details(event["alert"]["tinyId"])
    alert_description = alert_description_and_details_tuple[0]
    alert_details = alert_description_and_details_tuple[1]

    if str(action).lower() == "create":
        if "teamsToNotify" in alert_details.keys() and event["alert"]["username"] != "AWSLambda":
            print
            str(create_sub_alerts(alert_description, alert_details))
        else:
            print
            "Ignoring Action [" + action + "] since it\'s a create action for sub-alert."
    elif str(action).lower() == "acknowledge":
        if "rootAlertTinyId" in alert_details.keys():
            print
            str(add_note_to_the_root_alert(alert_details))
        else:
            print
            "Ignoring Action [" + action + "] since it\'s an acknowledge action for root alert."
    elif str(action).lower() == "close":
        if event["alert"]["username"] != "AWSLambda":
            print
            str(close_root_and_sub_alerts(alert_details))
        else:
            print
            "Ignoring close action since it's for an already closed alert."
    else:
        print
        "Ignoring Action [" + action + "]."

    return {"statusCode": 200}
