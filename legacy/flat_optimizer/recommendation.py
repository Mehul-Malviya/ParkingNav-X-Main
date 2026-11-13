def create_recommendation(best_option):
    if best_option is None:
        return "No available parking route was found."

    route_text = " → ".join(best_option["route"])

    message = (
        f"Recommended parking: {best_option['parking']}\n"
        f"Route: {route_text}\n"
        f"Route cost: {best_option['route_cost']}\n"
        f"Overall score: {best_option['total_cost']}"
    )

    return message