WEAPON_ELO_MULTIPLIER = {
    "AIM-9+": 4.0,
    "AIM-120C": 1.0,
    "AIM-120D": 1.0,
    "AIM-54": 6.0,
    "AIRS-T": 4.0,
    "AIM-9": 4.0,
    "GAU-8": 20.0,
    "Vulcan": 20.0,
    "AIM-7": 8.0,
    "AIM-9E": 30.0, #I'm not sure it's 9e or 9E......
    "GAU-22": 20.0,
    "M230": 20.0,
} #Using fixed multiplier currently to calculate elo change
AIRCRAFT_ELO_MULTIPLIER = {
    "F/A-26B": 4.0,
    "EF-24G": 8.0,
    "F-45A": 8.0,
    "T-55": 2.0,
    "AV-42C": 1.0,
}
ELO_CILING = 150 #Elo change will be capped at this value

class EloSystem:
    def __init__(self):
        self.elo_dict = {}

    def get_elo(self, playername: str) -> int:
        return self.elo_dict.get(playername, 1000)

    def set_elo(self, playername: str, elo: int) -> None:
        self.elo_dict[playername] = elo
    
    def calculate_elo_change_from_log(self,kill_playername, kill_aircraft, kill_faction, kill_weapon) -> int:
        mult_weapon = WEAPON_ELO_MULTIPLIER.get(kill_weapon, 1.0)
        mult_aircraft = AIRCRAFT_ELO_MULTIPLIER.get(kill_aircraft, 1.0)
        total_mult = mult_weapon * mult_aircraft
        if total_mult > ELO_CILING:
            total_mult = ELO_CILING
        return total_mult

EloSystem = EloSystem()