import time, subprocess
print("Waiting 1 minute for app to settle...")
time.sleep(60)

print("Running alembic...")
# Attempt Kudu REST API execution for migrations!
# Actually, az webapp create-remote-connection is hard, but we can try SSH via paramiko if we had it, or just use az rest
# Let's use Azure CLI SSH equivalent or az webapp ssh --command ... Wait, az webapp ssh doesn't have --command.
# Let's use Azure REST API
cmd = "az rest --method post --uri "https://app-narrative-merge-asia.scm.azurewebsites.net/api/command" --body "{\\"command\\":\\"alembic upgrade head\\", \\"dir\\":\\"/home/site/wwwroot\\"}""
subprocess.run(cmd, shell=True)
print("Done")
