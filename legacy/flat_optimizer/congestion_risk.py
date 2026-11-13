def calculate_congestion_risk(congestion_level):
    # Congestion must be between 0 and 1
    if congestion_level < 0 or congestion_level > 1:
        raise ValueError("Congestion level must be between 0 and 1.")

    # Return the congestion as a risk score
    return congestion_level