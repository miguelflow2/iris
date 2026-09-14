// TraductionEtiquettes.swift — traduction française des catégories les plus courantes du classifieur
// d'images d'iOS (VNClassifyImageRequest).
//
// Le classifieur rend des identifiants anglais (plus de mille). On ne traduit que les plus utiles pour se
// repérer ; une catégorie absente de cette table n'est PAS affichée en anglais au hasard : la phrase dit
// seulement qu'il existe d'autres catégories non traduites. Une clé qui n'existe pas dans la version du
// classifieur de l'iPhone ne fait rien (elle n'est simplement jamais rencontrée).

import Foundation

enum TraductionEtiquettes {
    static let francais: [String: String] = [
        // Lieux et extérieur
        "outdoor": "extérieur", "indoor": "intérieur", "street": "rue", "road": "route", "sidewalk": "trottoir",
        "crosswalk": "passage piéton", "parking_lot": "stationnement", "building": "bâtiment", "house": "maison",
        "structure": "construction", "bridge": "pont", "park": "parc", "sky": "ciel", "tree": "arbre",
        "plant": "plante", "grass": "herbe", "flower": "fleur", "garden": "jardin", "snow": "neige",
        "water": "eau", "beach": "plage", "mountain": "montagne", "forest": "forêt", "night_sky": "ciel de nuit",
        "sunset_sunrise": "coucher ou lever de soleil", "cityscape": "ville", "stairs": "escalier",
        "escalator": "escalier roulant", "elevator": "ascenseur", "door": "porte", "window": "fenêtre",
        "fence": "clôture", "wall": "mur", "ceiling": "plafond", "floor": "sol",
        // Pièces et intérieurs
        "room": "pièce", "kitchen": "cuisine", "bathroom": "salle de bain", "bedroom": "chambre",
        "living_room": "salon", "office": "bureau", "classroom": "salle de classe", "restaurant": "restaurant",
        "store": "magasin", "supermarket": "épicerie", "hallway": "couloir",
        // Transports et signalisation
        "vehicle": "véhicule", "car": "voiture", "bus": "autobus", "truck": "camion", "train": "train",
        "subway": "métro", "bicycle": "vélo", "motorcycle": "moto", "boat": "bateau", "airplane": "avion",
        "traffic_light": "feu de circulation", "sign": "panneau", "signage": "affichage", "stop_sign": "panneau d'arrêt",
        // Personnes et animaux
        "people": "personnes", "adult": "adulte", "child": "enfant", "baby": "bébé", "crowd": "foule",
        "animal": "animal", "dog": "chien", "cat": "chat", "bird": "oiseau", "horse": "cheval",
        // Objets du quotidien
        "furniture": "meuble", "chair": "chaise", "table": "table", "desk": "bureau (meuble)", "sofa": "canapé",
        "bed": "lit", "shelf": "étagère", "lamp": "lampe", "clock": "horloge", "mirror": "miroir",
        "sink": "évier", "toilet": "toilette", "refrigerator": "réfrigérateur", "oven": "four",
        "microwave": "four à micro-ondes", "bag": "sac", "backpack": "sac à dos", "umbrella": "parapluie",
        "wallet": "portefeuille", "keys": "clés", "key": "clé", "glasses": "lunettes", "sunglasses": "lunettes de soleil",
        "hat": "chapeau", "shoes": "chaussures", "clothing": "vêtement", "apparel": "vêtement", "jacket": "manteau",
        "shirt": "chandail", "box": "boîte", "container": "contenant", "bottle": "bouteille", "cup": "tasse",
        "mug": "tasse", "glass": "verre", "plate": "assiette", "bowl": "bol", "utensil": "ustensile",
        "tool": "outil", "scissors": "ciseaux", "toy": "jouet", "ball": "balle", "cane": "canne",
        "wheelchair": "fauteuil roulant", "medicine": "médicament", "pill": "comprimé",
        // Électronique et documents
        "computer": "ordinateur", "laptop": "ordinateur portable", "monitor": "écran", "screen": "écran",
        "television": "téléviseur", "phone": "téléphone", "cellphone": "téléphone cellulaire",
        "keyboard": "clavier", "computer_keyboard": "clavier", "remote_control": "télécommande",
        "consumer_electronics": "appareil électronique", "document": "document", "paper": "papier",
        "book": "livre", "magazine": "magazine", "newspaper": "journal", "receipt": "reçu", "menu": "menu",
        "text": "texte", "handwriting": "écriture à la main", "money": "argent", "currency": "billets de banque",
        "credit_card": "carte bancaire", "envelope": "enveloppe", "map": "carte",
        // Nourriture
        "food": "nourriture", "fruit": "fruit", "vegetable": "légume", "apple": "pomme", "banana": "banane",
        "orange": "orange", "bread": "pain", "sandwich": "sandwich", "pizza": "pizza", "cake": "gâteau",
        "dessert": "dessert", "meal": "repas", "drink": "boisson", "beverage": "boisson", "coffee": "café",
        "tea": "thé", "wine": "vin", "beer": "bière", "juice": "jus", "milk": "lait", "cheese": "fromage",
        "meat": "viande", "salad": "salade", "cereal": "céréales", "snack": "collation", "can": "canette",
    ]
}
