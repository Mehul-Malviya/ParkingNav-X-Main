def calculate_overflow_risk(occupied, capacity):
    if capacity <= 0:
        raise ValueError("Parking capacity must be greater than 0.")

    risk = occupied / capacity

    # A risk score cannot exceed 1
    return min(risk, 1)