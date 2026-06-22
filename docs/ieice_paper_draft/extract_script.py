import os
import fitz

target_dir = r"c:\Users\kapib\vscodegit\wild_animals\test2\docs\ieice_paper_draft\参考文献"
files = [
    "Towards_an_IoT-based_Deep_Learning_Architecture_for_Camera_Trap_Image_Classification.pdf",
    "Smart_Wildlife_Detection_and_Repulsion_System_using_Deep-Learning.pdf",
    "Proposal_and_Evaluation_of_A_Method_for_Automatically_Classifying_Images_of_Agricultural_Work_and_Animals_Acquired_with_Motion_Sensor_Cameras.pdf",
    "Eyes_in_the_Thicket_A_Neural_Gaze_for_Invisible_Wildlife_Encounters.pdf",
    "Development_of_a_Prevention_System_for_Beast_Damage_of_Agricultural_Products_Using_Deep_Learning.pdf",
    "Animal_Recognition_and_Identification_with_Deep_Convolutional_Neural_Networks_for_Automated_Wildlife_Monitoring.pdf",
    "Animal_Intrusion_Detection_Using_Yolo_V8.pdf",
    "Animal_Detection_Alert_System.pdf",
    "An_Efficient_Automated_Framework_for_Wildlife_Detection_and_Prevention_in_Agricultural_Zones_Nearer_to_Forest_Reserves.pdf",
    "A_Novel_Hierarchical_Edge_Computing_Solution_Based_on_Deep_Learning_for_Distributed_Image_Recognition_in_IoT_Systems.pdf"
]

output_file = r"c:\Users\kapib\vscodegit\wild_animals\test2\docs\ieice_paper_draft\extract_abstracts.txt"

with open(output_file, "w", encoding="utf-8") as out:
    for f in files:
        pdf_path = os.path.join(target_dir, f)
        out.write(f"=== File: {f} ===\n")
        try:
            doc = fitz.open(pdf_path)
            text = doc[0].get_text("text")[:2000] # 最初の2000文字を取得
            # 改行を少し綺麗にする
            text = text.replace('\n', ' ')
            out.write(text + "\n\n")
        except Exception as e:
            out.write(f"Error: {e}\n\n")

print(f"Extraction completed.")
