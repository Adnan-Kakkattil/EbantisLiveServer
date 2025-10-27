import asyncio
import os
import psutil
import logging
from live_monitor import client_main,sio
from client_register import monitor_ip_change
from utils.config import RUN_CLIENT_REGISTER,RUN_LIVE_MONITOR,CHECK_LIVE,get_tenant_name_from_json,get_user_email,check_live_connection_status,fetch_employee_transaction_id
 
 
 
 
 
 
# Event handler sets it to True
@sio.on('check_live_status_start')
async def on_check_live_status_start(data):
   
    CHECK_LIVE = True  # ✅ Set to True when event received
 
 
async def live_monitor_task():
    logging.info("Starting live monitor...")
    try:
        while True:
            user_email = get_user_email()
            tenant_name=get_tenant_name_from_json()
            user_name=os.getlogin()
            # tenant_id = get_tenant_id_by_name()
            print(tenant_name,user_name,user_email)
            employee_transaction_id = fetch_employee_transaction_id(tenant_name,user_name,user_email)
            # print("email",user_email,credentials,tenant_id)
            uuid = employee_transaction_id
            print("UUID",uuid)
 
            # if not credentials:
            #     logging.error("Failed to fetch credentials. Exiting...")
            #     return None
            if CHECK_LIVE:
 
               document = await check_live_connection_status(uuid)
            # document = live_monitor_db.find_one({"uuid": uuid})
               print("Document",document)
               status = False  # <-- Default assignment
 
               if document:
                    status = document.get("connection", False)
                    print(status)
 
               if status:
                    print("If status is True")
                    await client_main(uuid)
 
            logging.info("Live monitoring completed")
            await asyncio.sleep(3)
    except Exception as e:
        logging.error(f"An error occurred in live monitor: {e}")
 
 
async def client_register_task():
    logging.info("Starting  register client...")
    try:
        user_email = get_user_email()
        tenant_name=get_tenant_name_from_json()
        user_name=os.getlogin()
        # tenant_id = get_tenant_id_by_name()
        employee_transaction_id = fetch_employee_transaction_id(tenant_name,user_name,user_email)
        # print("email",user_email,credentials,tenant_id)
        uuid = employee_transaction_id
        print("UUID",uuid)
        # Run the sync function in a separate thread
        await asyncio.to_thread(monitor_ip_change,uuid)
        logging.info(" client register completed")
        await asyncio.sleep(3)
    except Exception as e:
        logging.error(f"An error occurred in registering client: {e}")
 
 
async def main():
    logging.info("Starting all tasks with prepared environment...")
 
    tasks = []
    if RUN_LIVE_MONITOR:
        tasks.append(asyncio.create_task(live_monitor_task()))
     
    if RUN_CLIENT_REGISTER:
        tasks.append(asyncio.create_task(client_register_task()))
 
    await asyncio.gather(*tasks)
 
 
def is_another_instance_running(exe_name):
    """
    Returns True if another instance of exe_name is running (excluding this process).
    """
    current_pid = os.getpid()
    count = 0
    for proc in psutil.process_iter(['name', 'exe', 'pid']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == exe_name.lower():
                if proc.info['pid'] != current_pid:
                    count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return count > 1
 
 
if __name__ == "__main__":
    try:
        exe_name = 'RemoteDesktop.exe'
        # if not is_another_instance_running(exe_name):
        asyncio.run(main())
        # else:
            # print("Already running")
    except Exception as e:
        pass
# if __name__ == "__main__":
 
 
#     asyncio.run(main())
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
# import asyncio
# import os
# import psutil
# import logging
# from live_monitor import client_main
# from client_register import monitor_ip_change
# from utils.config import RUN_CLIENT_REGISTER,RUN_LIVE_MONITOR,get_cred,get_user_email,get_tenant_id_by_name,get_employee_transaction_id,check_live_connection_status
 
# async def live_monitor_task():
#     logging.info("Starting live monitor...")
#     try:
#         while True:
#             credentials = get_cred()
#             print("credentials",credentials)      
#             user_email = get_user_email()
           
#             tenant_id = get_tenant_id_by_name(credentials)
#             employee_transaction_id = get_employee_transaction_id()
#             # print("email",user_email,credentials,tenant_id)
#             uuid = employee_transaction_id
#             print("UUID",uuid)
 
#             if not credentials:
#                 logging.error("Failed to fetch credentials. Exiting...")
#                 return None
 
#             live_monitor_db = check_live_connection_status(credentials, uuid)
#             document = live_monitor_db.find_one({"uuid": uuid})
#             print("Document",document)
#             status = False  # <-- Default assignment
 
#             if document:
#                 status = document.get("connection", False)
#                 print(status)
 
#             if status:
#                 print("If status is True")
#                 await client_main(live_monitor_db, uuid)
 
#             logging.info("Live monitoring completed")
#             await asyncio.sleep(3)
#     except Exception as e:
#         logging.error(f"An error occurred in live monitor: {e}")
 
 
# async def client_register_task():
#     logging.info("Starting  register client...")
#     try:
#         # Run the sync function in a separate thread
#         await asyncio.to_thread(monitor_ip_change)
#         logging.info(" client register completed")
#     except Exception as e:
#         logging.error(f"An error occurred in registering client: {e}")
 
 
# async def main():
#     logging.info("Starting all tasks with prepared environment...")
 
#     tasks = []
#     if RUN_LIVE_MONITOR:
#         tasks.append(asyncio.create_task(live_monitor_task()))
     
#     if RUN_CLIENT_REGISTER:
#         tasks.append(asyncio.create_task(client_register_task()))
 
#     await asyncio.gather(*tasks)
 
 
# def is_another_instance_running(exe_name):
#     """
#     Returns True if another instance of exe_name is running (excluding this process).
#     """
#     current_pid = os.getpid()
#     count = 0
#     for proc in psutil.process_iter(['name', 'exe', 'pid']):
#         try:
#             if proc.info['name'] and proc.info['name'].lower() == exe_name.lower():
#                 if proc.info['pid'] != current_pid:
#                     count += 1
#         except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
#             continue
#     return count > 1
 
 
# if __name__ == "__main__":
#     try:
#         exe_name = 'RemoteDesktop.exe'
#         if not is_another_instance_running(exe_name):
#             asyncio.run(main())
#         else:
#             print("Already running")
#     except Exception as e:
#         pass
# # if __name__ == "__main__":
 
 
# #     asyncio.run(main())
 