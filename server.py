@router.post("/LiveServer/")
async def send_uuid_to_centralized_server(data: dict):
    try:
 
 
       
        db = mongo.get_database("EbantisV3")
        collection = db["Client_uuid"]
 
        if ENCRYPTION == True:
            print("true block")
            if "data" not in data:
                raise HTTPException(status_code=400, detail="'data' key is missing in the request")
 
            emp = aes.decrypt_string(data["data"])
            emp_dict = json.loads(emp)
            emp_id = int(emp_dict["EmpId"])
            live_key=int(emp_dict["LiveKey"])
            print(live_key)
            print("EMPID",emp_id)
        else:
            if "EmpId" not in data:
                raise HTTPException(status_code=400, detail="'EmpId' key is missing in the request")
 
            emp_id = int(data["EmpId"])
            print(emp_id)
            live_key=int(data["LiveKey"])
            print(live_key)
 
        document = await collection.find_one({"EmployeeTransactionId": emp_id})
        print("Document",document)
 
        if not document:
            raise HTTPException(status_code=404, detail="Employee not found")
 
        UUID = document["uuid"]
        response = requests.post(
    f"{CENTRALIZED_SERVER_URL}/start_monitor/",
    json={"uuid": UUID}
)
 
        if response.status_code == 200:
            print("Client notified to start monitoring")
        status = document["Status"]
 
        # Update MongoDB to set connection: True
        await collection.update_one(
            {"uuid": UUID},
            {"$set": {"connection": True}}
        )
        print(f"Updated connection status for UUID: {UUID}")

        # REMOVED: Unnecessary 20-second wait + MongoDB polling
        # Instead, proceed directly to request client from centralized server
        # The client will start via Socket.IO push notification (see client.py)
        
        print(f"[REQUEST] Proceeding to request client from centralized server")
        response = requests.post(
            f"{CENTRALIZED_SERVER_URL}/request_client/", 
            json={"uuid": UUID, "key": live_key},
            timeout=10  # Add timeout to prevent hanging
        )
        print(f"[REQUEST] Response: {response.json()}")
       
        if response.status_code == 200:
            print(f"Client info: {response.json()}")
            return {"message": "success"}
        else:
            # If centralized server fails, reset connection status
            await collection.update_one(
                {"uuid": UUID},
                {"$set": {"connection": False}}
            )
            print(f"Error: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Failed to contact centralized server")
 
    except Exception as e:
        print(f"Failed to send UUID to centralized server: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")