def is_parking_available(parking_details):
    capacity = parking_details["capacity"]
    occupied = parking_details["occupied"]

    if capacity <= 0:
        raise ValueError("Parking capacity must be greater than 0.")

    if occupied < 0:
        raise ValueError("Occupied spaces cannot be negative.")

    return occupied < capacity