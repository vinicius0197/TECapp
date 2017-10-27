import pymysql.cursors
import datetime
from flask import Flask, flash, redirect, render_template, request, session, url_for, make_response
import os
import json
import requests

from slackclient import SlackClient

from zappa.async import task

# Slack tokens from environment variables
SLACK_BOT_TOKEN = os.environ["SLACK_API_TOKEN"]
SLACK_VERIFICATION_TOKEN = os.environ["SLACK_VERIFICATION_TOKEN"]

# information on database from environment variables
HOST_DB = os.environ["HOST_DB"]
USER_DB = os.environ["USER_DB"]
PASS_DB = os.environ["PASS_DB"]
NAME_DB = os.environ["NAME_DB"]

slack_client = SlackClient(SLACK_BOT_TOKEN)
app = Flask(__name__)

@task
def status(response_url):
	conn = pymysql.connect(host=HOST_DB,    
                     user=USER_DB,         
                     passwd=PASS_DB,  
                     db=NAME_DB)
	db = conn.cursor(pymysql.cursors.DictCursor)

	db.execute("SELECT * FROM projetos JOIN historico ON projetos.id = historico.id")
	db.execute("SELECT * FROM projetos")
	project_list = db.fetchall()

	# code for deleting previous /stat message (refreshing)

	for project in project_list:
		db.execute("SELECT status FROM historico WHERE id = %s", [project['id']])
		status_query = db.fetchall()
		statusList = []

		for status in status_query:
			item = {"value": "- " + status['status']}
			statusList.append(item)

		responsavel = project['person']
		projeto = project['project']
		data = project['date']

		payload = {
			"attachments":[
				{
					"fallback": "Required plain-text summary of the attachment.",
					"title": projeto + ' - ' + data,
					"text": "Responsavel: " + responsavel,
					"fields": statusList,
					"color": "#FE2E2E",
					"footer": "TECSlack App"
				}
			]
		}
		requests.post(response_url,data=json.dumps(payload))

	db.close()
	

@task
def data(user_id, trigger_id):
	
	open_dialog = slack_client.api_call(
		"dialog.open",
		trigger_id=trigger_id,
		dialog={
			"title": "Projetos TECMEC",
			"submit_label": "Enviar",
			"callback_id": "envio_projeto",
			"elements": [
			{
				"label": "Responsável",
				"name": "responsavel",
				"type": "text",
			},
			{
				"label": "Projeto",
				"name": "projeto",
				"type": "text",
			},
			{
				"label": "Data de chegada",
				"name": "data",
				"type": "text",
			}
			]
		}
		)

	print(open_dialog)


@task
def manage_project(req):
	conn = pymysql.connect(host=HOST_DB,    
                     user=USER_DB,         
                     passwd=PASS_DB,  
                     db=NAME_DB)
	db = conn.cursor(pymysql.cursors.DictCursor)

	if req["callback_id"] == "envio_projeto":
		user = req["submission"]["responsavel"]
		project = req["submission"]["projeto"]
		date = req["submission"]["data"]

		# Ensures date is in the format XX/YY/ZZ
		try:
			date = datetime.datetime.strptime(date, '%d/%m/%Y').strftime('%d/%m/%Y')
			db.execute("INSERT INTO projetos (person, project, date) VALUES (%s, %s, %s)   ", [user, project, date])
			conn.commit()
			db.close()
		except ValueError:
			return make_response("Data incorreta", 200)
			db.close()

		# code for sending message to all team with new project added

	elif req["callback_id"] == "atualizar_projeto":
		sel_project = req["submission"]["update_project"]
		db.execute("SELECT id FROM projetos WHERE project = %s", [sel_project])
		get_id = db.fetchone()
		project_id = get_id['id']

		db.execute("INSERT INTO historico (id, status) VALUES (%s, %s)", [project_id, req["submission"]["status"]])
		conn.commit()
		db.close()

		# code for sending mesage to all team with status update

	elif req["callback_id"] == "remover_projeto":
		sel_project = req["submission"]["update_project"]
		db.execute("SELECT id FROM projetos WHERE project = %s", [sel_project])
		get_id = db.fetchone()
		project_id = get_id['id']

		db.execute("DELETE FROM projetos WHERE id = %s", [project_id])
		conn.commit()
		db.close()


@task
def update_project(trigger_id, user_id):
	# Initializing database
	conn = pymysql.connect(host=HOST_DB,    
                     user=USER_DB,         
                     passwd=PASS_DB,  
                     db=NAME_DB)
	db = conn.cursor(pymysql.cursors.DictCursor)
	
	db.execute("SELECT * FROM projetos")
	project_list = db.fetchall()

	data = []
	for project in project_list:
		item = {"label": project['project'], "value": project['project']}
		data.append(item)


	open_dialog = slack_client.api_call(
		"dialog.open",
		trigger_id=trigger_id,
		dialog={
			"title": "Projetos TECMEC",
			"submit_label": "Enviar",
			"callback_id": "atualizar_projeto",
			"elements": [
			{
				"label": "Projeto",
				"type": "select",
				"name": "update_project",
				"placeholder": "Selecione um projeto",
				"options": data
			},
			{
				"label": "Status",
				"name": "status",
				"type": "textarea",
				"hint": "Status da negociação"
			}
			]
		}
		)

	print(open_dialog)

	db.close()


@task
def remove_project(trigger_id):
	# Initializing database
	conn = pymysql.connect(host=HOST_DB,    
                     user=USER_DB,         
                     passwd=PASS_DB,  
                     db=NAME_DB)
	db = conn.cursor(pymysql.cursors.DictCursor)

	db.execute("SELECT * FROM projetos")
	project_list = db.fetchall()

	data = []
	for project in project_list:
		item = {"label": project['project'], "value": project['project']}
		data.append(item)

	open_dialog = slack_client.api_call(
		"dialog.open",
		trigger_id=trigger_id,
		dialog={
			"title": "Projetos TECMEC",
			"submit_label": "Remover",
			"callback_id": "remover_projeto",
			"elements": [
			{
				"label": "Projeto",
				"type": "select",
				"name": "update_project",
				"placeholder": "Selecione um projeto para remover",
				"options": data 
			}
			]
		}
		)

	print(open_dialog)

	db.close()

# Main function. Because Slack timeout is only 3000ms, this function returns a response immediately while
# other function takes care of the most slow tasks 
@app.route('/<slash>', methods=['POST','GET'])
def receptionist(slash):

	response_url = request.form.get("response_url")
	user_id = str(request.form.get('user_id'))
	trigger_id = str(request.form.get('trigger_id'))

	if slash == 'projeto':
		data(user_id, trigger_id)
	elif slash =='stat':
		status(response_url)
	elif slash == 'criar_projeto':
		req = json.loads(request.form["payload"])
		manage_project(req)
	elif slash == 'atualizar_projeto':
		trigger_id = request.form.get('trigger_id')
		user_id = user_id = str(request.form.get('user_id'))
		update_project(trigger_id, user_id)

	elif slash == 'remover_projeto':
		trigger_id = request.form.get('trigger_id')
		remove_project(trigger_id)

	return make_response("", 200)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)


