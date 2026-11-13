from optimization.constraints.parking_constraints import is_parking_available


def first_available_parking(parking_data):
    for parking_name, details in parking_data.items():
        if is_parking_available(details):
            return parking_name

    return None