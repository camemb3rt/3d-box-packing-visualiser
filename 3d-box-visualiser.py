import tkinter as tk
from tkinter import ttk, scrolledtext
import re
import itertools
import math
from collections import namedtuple
import json
import os

# --- Constants & Data Classes ---
STATE_FILE = "packer_state.json"
COLOR_PALETTE = [
    "#FF7F50", "#FFD700", "#ADFF2F", "#00FFFF",  # Orange, Gold, Green-Yellow, Cyan
    "#1E90FF", "#BA55D3", "#FF69B4", "#D2B48C",  # Dodger Blue, Medium Orchid, Hot Pink, Tan
    "#A9A9A9", "#4682B4", "#B0C4DE", "#20B2AA",  # Dark Gray, Steel Blue, Light Steel Blue, Light Sea Green
    "#8B4513", "#708090", "#800080", "#000000"   # Saddle Brown, Slate Gray, Purple, Black
]
SAMPLE_DIMS = """
Common Dimensions (L x W x H / Weight):
- Nendoroid: 175mm x 135mm x 90mm / 242g
- Funko POP!: 165mm x 115mm x 90mm / 150g
- Blu-ray Case: 170mm x 135mm x 15mm / 100g
- Shoe Box (Avg): 330mm x 200mm x 120mm / 300g
"""

# Box now includes 'color_hex'
Box = namedtuple('Box', ['name', 'l', 'w', 'h', 'weight', 'volume', 'color_hex'])
Container = namedtuple('Container', ['l', 'w', 'h', 'volume'])
PlacedBox = namedtuple('PlacedBox', ['box', 'x', 'y', 'z', 'l', 'w', 'h'])

# --- Packing Logic (Remains the same) ---

def check_overlap(placed_boxes, x, y, z, l, w, h):
    b1_x1, b1_y1, b1_z1 = x, y, z
    b1_x2, b1_y2, b1_z2 = x + l, y + w, z + h

    for p_box in placed_boxes:
        b2_x1, b2_y1, b2_z1 = p_box.x, p_box.y, p_box.z
        # Corrected Z dimension check in the overlap calculation
        b2_x2, b2_y2, b2_z2 = p_box.x + p_box.l, p_box.y + p_box.w, p_box.z + p_box.h
        no_overlap_x = b1_x2 <= b2_x1 or b1_x1 >= b2_x2
        no_overlap_y = b1_y2 <= b2_y1 or b1_y1 >= b2_y2
        no_overlap_z = b1_z2 <= b2_z1 or b1_z1 >= b2_z2

        if not (no_overlap_x or no_overlap_y or no_overlap_z):
            return True
    return False

def pack_recursive_helper(boxes_left, container, placed_boxes):
    if not boxes_left:
        return placed_boxes

    box_to_place = boxes_left[0]
    remaining_boxes = boxes_left[1:]
    
    # Generate potential anchor points: container origin and all corners of placed boxes
    anchor_points = [(0, 0, 0)]
    if placed_boxes:
        for p in placed_boxes:
            # Points where a new box might start to fit flush against existing faces
            anchor_points.append((p.x + p.l, p.y, p.z))
            anchor_points.append((p.x, p.y + p.w, p.z))
            anchor_points.append((p.x, p.y, p.z + p.h))
    
    unique_anchors = sorted(list(set(anchor_points)))

    for (ax, ay, az) in unique_anchors:
        dims = (box_to_place.l, box_to_place.w, box_to_place.h)
        # Check all 6 rotations
        rotations = set(itertools.permutations(dims))

        for (l, w, h) in rotations:
            # 1. Check container bounds
            if ax + l > container.l or ay + w > container.w or az + h > container.h:
                continue
            # 2. Check overlap with existing boxes
            if check_overlap(placed_boxes, ax, ay, az, l, w, h):
                continue
            
            # If fit is valid, place the box and recurse
            new_placed_box = PlacedBox(box=box_to_place, x=ax, y=ay, z=az, l=l, w=w, h=h)
            new_placed_list = placed_boxes + [new_placed_box]
            recursive_result = pack_recursive_helper(remaining_boxes, container, new_placed_list)
            if recursive_result is not None:
                return recursive_result

    return None

def check_fit(boxes_to_pack, container):
    # Sort by volume descending for better greedy placement
    sorted_boxes = sorted(boxes_to_pack, key=lambda b: b.volume, reverse=True)
    
    # Quick check if any single box is too big for the container dimensions
    for box in sorted_boxes:
        can_fit_at_all = False
        dims = (box.l, box.w, box.h)
        rotations = set(itertools.permutations(dims))
        for (l, w, h) in rotations:
            if l <= container.l and w <= container.w and h <= container.h:
                can_fit_at_all = True
                break
        if not can_fit_at_all:
            return None # A box cannot fit even when rotated
            
    # Attempt the recursive packing
    return pack_recursive_helper(sorted_boxes, container, [])

# --- Helper Functions (Updated to use L+W+H <= total_sum) ---

def generate_containers(self, total_sum, max_dim, min_dim, increment):
    """
    Generates unique container dimensions (L, W, H) that satisfy all rules:
    1. min_dim <= L, W, H <= max_dim
    2. L, W, H must be multiples of increment.
    3. L + W + H <= total_sum (Updated constraint)
    4. Only returns unique, sorted (L<=W<=H) dimensions.
    """
    valid_containers = set()
    if increment <= 0: return []
        
    valid_steps = list(range(min_dim, max_dim + 1, increment))

    for l in valid_steps:
        for w in valid_steps:
            for h in valid_steps:
                # Check the new constraint: L + W + H must be <= total_sum
                if l + w + h <= total_sum:
                    # Store the dimensions as a sorted tuple to guarantee uniqueness (L, W, H)
                    dims = tuple(sorted([l, w, h]))
                    valid_containers.add(dims)
                # Optimization: since h is increasing, if we exceed the sum, 
                # we can break the inner loop for this (l, w) combination
                else:
                    break 
    
    return [Container(l=d[0], w=d[1], h=d[2], volume=(d[0]*d[1]*d[2])) for d in valid_containers]

def parse_box_string(text, name, color_hex):
    # This regex handles formats like "265x280x175/1000" OR "265mm x 280mm x 175mm / 1000g"
    match = re.search(
        r"(\d+)\s*m*m?\s*[xX]\s*(\d+)\s*m*m?\s*[xX]\s*(\d+)\s*m*m?\s*/\s*(\d+)\s*g?",
        text.replace(" ", "")
    )
    
    if not match: return None
        
    try:
        l = int(match.group(1))
        w = int(match.group(2))
        h = int(match.group(3))
        weight = int(match.group(4))
        volume = l * w * h
        # Return Box with the color_hex field
        return Box(name=name, l=l, w=w, h=h, weight=weight, volume=volume, color_hex=color_hex)
    except Exception as e:
        print(f"Error parsing box string: {e}")
        return None

# --- GUI Application ---

class PackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("3D Box Packing Visualiser")
        self.geometry("900x700")

        self.box_entries = []
        self.containers = []
        self.successful_fits = []
        
        self.setup_gui()
        self.load_state() # Load state after GUI is built
        
        # Save state when the window is closed
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- Session Management ---

    def on_closing(self):
        """Saves state before closing the application."""
        self.save_state()
        self.destroy()

    def save_state(self):
        """Collects all user inputs and saves them to a JSON file."""
        state = {}
        
        # 1. Box Inputs
        state['boxes'] = []
        for entry in self.box_entries:
            state['boxes'].append({
                'name': entry['name'].get(),
                'dims': entry['dims'].get(),
                'color': entry['color_var'].get()
            })

        # 2. Rule Inputs
        state['rules'] = {
            'total_sum': self.total_sum_entry.get(),
            'max_dim': self.max_dim_entry.get(),
            'min_dim': self.min_dim_entry.get(),
            'increment': self.increment_entry.get(),
            'max_weight': self.weight_entry.get()
        }

        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            print(f"Error saving state: {e}")

    def load_state(self):
        """Loads inputs from the JSON file and updates the GUI."""
        if not os.path.exists(STATE_FILE):
            return

        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            
            # 1. Box Inputs
            if 'boxes' in state:
                for i, box_data in enumerate(state['boxes']):
                    if i < len(self.box_entries):
                        entry = self.box_entries[i]
                        entry['name'].delete(0, tk.END)
                        entry['name'].insert(0, box_data.get('name', f"Box {i+1}"))
                        entry['dims'].delete(0, tk.END)
                        entry['dims'].insert(0, box_data.get('dims', ''))
                        
                        # Set color button and StringVar
                        color = box_data.get('color', COLOR_PALETTE[i % 16])
                        entry['color_var'].set(color)
                        entry['color_button'].config(bg=color)

            # 2. Rule Inputs
            if 'rules' in state:
                rules = state['rules']
                self.total_sum_entry.delete(0, tk.END); self.total_sum_entry.insert(0, rules.get('total_sum', '900'))
                self.max_dim_entry.delete(0, tk.END); self.max_dim_entry.insert(0, rules.get('max_dim', '600'))
                self.min_dim_entry.delete(0, tk.END); self.min_dim_entry.insert(0, rules.get('min_dim', '50'))
                self.increment_entry.delete(0, tk.END); self.increment_entry.insert(0, rules.get('increment', '50'))
                self.weight_entry.delete(0, tk.END); self.weight_entry.insert(0, rules.get('max_weight', '10000'))

        except Exception as e:
            print(f"Error loading state: {e}")
            # If loading fails, clear the state file to prevent continuous errors
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass # File might not exist

    # --- Color Picker Dialog ---
    
    def show_color_picker(self, box_index):
        """Opens a top-level window with the 4x4 color grid."""
        
        # Create Toplevel window
        picker_window = tk.Toplevel(self)
        picker_window.title("Select Color")
        picker_window.transient(self) # Keep it on top of main window
        picker_window.grab_set() # Modal behavior
        
        # Center the picker window over the main window (approx)
        main_x = self.winfo_x()
        main_y = self.winfo_y()
        main_w = self.winfo_width()
        main_h = self.winfo_height()
        picker_w, picker_h = 200, 200 # approximate size
        picker_window.geometry(f'+{main_x + (main_w - picker_w)//2}+{main_y + (main_h - picker_h)//2}')

        def select_color(color_hex):
            """Callback function to set the new color and close the picker."""
            entry = self.box_entries[box_index]
            entry['color_var'].set(color_hex)
            entry['color_button'].config(bg=color_hex)
            picker_window.destroy()

        # Create the grid canvas
        color_grid_frame = ttk.Frame(picker_window, padding=10)
        color_grid_frame.pack()

        rows, cols = 4, 4
        swatch_size = 35

        for i, color_hex in enumerate(COLOR_PALETTE):
            r = i // cols
            c = i % cols
            
            # Create a small canvas for the color swatch
            swatch = tk.Canvas(color_grid_frame, width=swatch_size, height=swatch_size, bg=color_hex, highlightthickness=1, highlightbackground="gray")
            swatch.grid(row=r, column=c, padx=3, pady=3)
            
            # Bind click event to the select_color function
            swatch.bind("<Button-1>", lambda event, color=color_hex: select_color(color))

        picker_window.wait_window(picker_window) # Wait for picker to close

    # --- GUI Setup ---

    def setup_gui(self):
        # Main frame
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left side: Inputs
        left_frame = ttk.Frame(main_frame, width=350)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_frame.pack_propagate(False)

        # Box inputs frame
        box_frame = ttk.LabelFrame(left_frame, text="Box Inputs (Name, Color, Dimensions)")
        box_frame.pack(fill=tk.X, pady=10)

        for i in range(10):
            frame = ttk.Frame(box_frame)
            frame.pack(fill=tk.X, padx=5, pady=2)
            
            # 1. Color Button (Replaces Combobox)
            color_var = tk.StringVar(value=COLOR_PALETTE[i % len(COLOR_PALETTE)])
            color_button = tk.Button(frame, width=3, bg=color_var.get(), relief=tk.RAISED,
                                     command=lambda i=i: self.show_color_picker(i))
            color_button.pack(side=tk.LEFT, padx=(0, 5))
            
            # 2. Name Entry
            name_entry = ttk.Entry(frame, width=10)
            name_entry.insert(0, f"Box {i+1}")
            name_entry.pack(side=tk.LEFT, padx=(0, 5))

            # 3. Dimensions Entry
            dim_entry = ttk.Entry(frame, width=25)
            dim_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            self.box_entries.append({
                'color_var': color_var, 
                'color_button': color_button, 
                'name': name_entry, 
                'dims': dim_entry
            })

        # Setting default text to the requested full format
        self.box_entries[0]['dims'].insert(0, "265mm x 280mm x 175mm / 1000g")
        self.box_entries[1]['dims'].insert(0, "185mm x 245mm x 305mm / 800g")

        # Container Rules
        rules_frame = ttk.LabelFrame(left_frame, text="Container Rules (mm / g)")
        rules_frame.pack(fill=tk.X, pady=5)

        def add_rule_entry(parent, text, default_value):
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, padx=5, pady=2)
            ttk.Label(frame, text=text, width=18).pack(side=tk.LEFT)
            entry = ttk.Entry(frame, width=10)
            entry.insert(0, default_value)
            entry.pack(side=tk.LEFT)
            return entry

        # Updated Label for L+W+H <= Max Sum
        self.total_sum_entry = add_rule_entry(rules_frame, "Max Sum (L+W+H):", "900")
        self.max_dim_entry = add_rule_entry(rules_frame, "Max Dimension:", "600")
        self.min_dim_entry = add_rule_entry(rules_frame, "Min Dimension:", "50")
        self.increment_entry = add_rule_entry(rules_frame, "Increment:", "50")

        # Weight limit
        weight_frame = ttk.Frame(rules_frame)
        weight_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(weight_frame, text="Max Weight (g):", width=18).pack(side=tk.LEFT)
        self.weight_entry = ttk.Entry(weight_frame, width=10)
        self.weight_entry.insert(0, "10000")
        self.weight_entry.pack(side=tk.LEFT)


        # Run button
        self.run_button = ttk.Button(left_frame, text="Find Fit", command=self.run_packing)
        self.run_button.pack(fill=tk.X, pady=10)
        
        # --- Sample Dimensions List (Bottom Left) ---
        sample_frame = ttk.LabelFrame(left_frame, text="Sample Dimensions Reference")
        sample_frame.pack(fill=tk.BOTH, pady=(5,0), expand=True)
        
        sample_text = scrolledtext.ScrolledText(sample_frame, wrap=tk.WORD, height=8, width=1, font=('Consolas', 9))
        sample_text.insert(tk.END, SAMPLE_DIMS.strip())
        sample_text.configure(state='disabled', background='#f0f0f0')
        sample_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)


        # Right side: Results (Tabs)
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # --- Tab 1: Log ---
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text="Log")
        
        self.result_text = scrolledtext.ScrolledText(log_tab, wrap=tk.WORD, height=25)
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.result_text.insert(tk.END, "Ready to pack. State will load automatically.\n")
        self.result_text.configure(state='disabled')
        
        # --- Tab 2: Visualizer ---
        viz_tab = ttk.Frame(self.notebook)
        self.notebook.add(viz_tab, text="Visualizer")
        
        viz_controls = ttk.Frame(viz_tab)
        viz_controls.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(viz_controls, text="Select Fit:").pack(side=tk.LEFT)
        self.viz_combo = ttk.Combobox(viz_controls, state="readonly", width=50)
        self.viz_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.viz_combo.bind("<<ComboboxSelected>>", self.display_fit)
        
        self.viz_canvas = tk.Canvas(viz_tab, bg="white", highlightthickness=0)
        self.viz_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    # --- Packing Run and Display Logic (Updated to use StringVar for color) ---

    def log(self, message):
        self.result_text.configure(state='normal')
        self.result_text.insert(tk.END, message + "\n")
        self.result_text.see(tk.END)
        self.result_text.configure(state='disabled')
        self.update_idletasks()

    def run_packing(self):
        self.run_button.config(state='disabled', text="Working...")
        self.result_text.configure(state='normal'); self.result_text.delete('1.0', tk.END); self.result_text.configure(state='disabled')
        self.successful_fits = []
        self.viz_combo.set(""); self.viz_combo['values'] = []; self.viz_canvas.delete("all")

        self.log("Starting packing process...")

        try:
            total_sum = int(self.total_sum_entry.get())
            max_dim = int(self.max_dim_entry.get())
            min_dim = int(self.min_dim_entry.get())
            increment = int(self.increment_entry.get())
            max_weight = float(self.weight_entry.get())
        except ValueError:
            self.log("Error: Invalid numeric input in rules section.")
            self.run_button.config(state='normal', text="Find Fit")
            return
        
        # The generate_containers function now handles the L+W+H <= total_sum logic
        self.containers = generate_containers(None, total_sum, max_dim, min_dim, increment)
        if not self.containers:
            self.log("Error: No valid containers generated with these rules.")
            self.run_button.config(state='normal', text="Find Fit")
            return
        
        input_boxes = []
        for i, entry in enumerate(self.box_entries):
            name = entry['name'].get()
            text = entry['dims'].get()
            color_hex = entry['color_var'].get()
            
            if text:
                box = parse_box_string(text, name, color_hex)
                if box:
                    input_boxes.append(box)
                else:
                    self.log(f"Error: Could not parse dims for '{name}'. Skipping.")
        
        if len(input_boxes) < 2:
            self.log("Error: Need at least 2 valid boxes to run a combination check.")
            self.run_button.config(state='normal', text="Find Fit")
            return

        self.log(f"Checking {len(input_boxes)} boxes against {len(self.containers)} container types...")
        self.log("-" * 30)

        found_solutions = 0
        
        for k in range(2, len(input_boxes) + 1):
            self.log(f"--- Checking combinations of {k} boxes ---")
            
            for box_combination in itertools.combinations(input_boxes, k):
                total_weight = sum(b.weight for b in box_combination)
                if total_weight > max_weight: continue
                
                total_volume = sum(b.volume for b in box_combination)
                
                is_fit_found = False
                for container in self.containers:
                    if total_volume > container.volume: continue
                    placed_boxes_list = check_fit(list(box_combination), container)
                    
                    if placed_boxes_list is not None:
                        is_fit_found = True
                        found_solutions += 1
                        box_names = ", ".join([b.name for b in box_combination])
                        free_volume = container.volume - total_volume
                        fit_name = f"Fit #{found_solutions}: ({box_names}) in {container.l}x{container.w}x{container.h}"
                        
                        self.log(f"Found Fit #{found_solutions}!")
                        self.log(f"  Container: {container.l} x {container.w} x {container.h} mm")
                        
                        self.successful_fits.append({'name': fit_name, 'container': container, 'boxes': placed_boxes_list})
                        break
                
        self.log("-" * 30)
        self.log(f"Search complete. Found {found_solutions} valid packing solutions.")
        
        if self.successful_fits:
            self.viz_combo['values'] = [f['name'] for f in self.successful_fits]
            self.viz_combo.current(0)
            self.display_fit(None)
            self.notebook.select(1)
            
        self.run_button.config(state='normal', text="Find Fit")

    def display_fit(self, event):
        if not self.successful_fits: return
            
        selected_index = self.viz_combo.current()
        if selected_index == -1: return

        fit_data = self.successful_fits[selected_index]
        self.draw_projections(fit_data['container'], fit_data['boxes'])

    def draw_projections(self, container, placed_boxes):
        self.viz_canvas.delete("all")
        self.viz_canvas.update_idletasks()
        canvas_w = self.viz_canvas.winfo_width()
        canvas_h = self.viz_canvas.winfo_height()
        
        if canvas_w < 50 or canvas_h < 50: return

        PADDING = 50
        LEFT_MEASURE_OFFSET = 30
        BOTTOM_MEASUREMENT_SPACE = 25
        TITLE_HEIGHT = 20
        V_GAP = 40
        
        # Calculate available drawing area for two views side-by-side
        available_drawing_w = canvas_w - PADDING * 2 - LEFT_MEASURE_OFFSET * 2 - V_GAP
        vp_w = available_drawing_w / 2 # Width of each view
        available_drawing_h = canvas_h - PADDING * 2 - TITLE_HEIGHT * 2 - V_GAP - BOTTOM_MEASUREMENT_SPACE
        vp_h = available_drawing_h / 2 # Height of X-Z and Y-Z views
        
        # Top View (X-Y) - Takes up the space of two vertical views
        vp1_x = PADDING + LEFT_MEASURE_OFFSET 
        vp1_y = PADDING + TITLE_HEIGHT
        vp1_h_total = vp_h * 2 + V_GAP + BOTTOM_MEASUREMENT_SPACE # Adjusted height for the visualizer space
        self.viz_canvas.create_text(vp1_x + vp_w/2, PADDING, text="Top View (X-Y)", font=("TkDefaultFont", 12, "bold"))
        self._draw_one_view(vp1_x, vp1_y, vp_w, vp1_h_total, container.l, container.w, placed_boxes, 'x', 'y', 'l', 'w', flip_v=False, measure_offset_v=LEFT_MEASURE_OFFSET, measure_offset_h=BOTTOM_MEASUREMENT_SPACE, draw_box_dims=False)
        
        # Front View (X-Z) - Top Right
        vp2_x = vp1_x + vp_w + V_GAP + LEFT_MEASURE_OFFSET 
        vp2_y = PADDING + TITLE_HEIGHT
        self.viz_canvas.create_text(vp2_x + vp_w/2, PADDING, text="Front View (X-Z)", font=("TkDefaultFont", 12, "bold"))
        self._draw_one_view(vp2_x, vp2_y, vp_w, vp_h, container.l, container.h, placed_boxes, 'x', 'z', 'l', 'h', flip_v=True, measure_offset_v=LEFT_MEASURE_OFFSET, measure_offset_h=BOTTOM_MEASUREMENT_SPACE, draw_box_dims=True)

        # Side View (Y-Z) - Bottom Right
        vp3_x = vp2_x
        vp3_title_y = vp2_y + vp_h + V_GAP
        vp3_y = vp3_title_y + TITLE_HEIGHT 
        self.viz_canvas.create_text(vp3_x + vp_w/2, vp3_title_y, text="Side View (Y-Z)", font=("TkDefaultFont", 12, "bold"))
        self._draw_one_view(vp3_x, vp3_y, vp_w, vp_h, container.w, container.h, placed_boxes, 'y', 'z', 'w', 'h', flip_v=True, measure_offset_v=LEFT_MEASURE_OFFSET, measure_offset_h=BOTTOM_MEASUREMENT_SPACE, draw_box_dims=True)


    def _draw_one_view(self, x_offset, y_offset, vp_w, vp_h, dim1_max, dim2_max, boxes, d1_attr, d2_attr, l1_attr, l2_attr, flip_v, measure_offset_v, measure_offset_h, draw_box_dims):
        BUFFER_FACTOR = 0.95
        if dim1_max == 0 or dim2_max == 0: return

        # Scaling to fit the view pane
        base_scale = min(vp_w / dim1_max, vp_h / dim2_max) * BUFFER_FACTOR
        scale = base_scale
        
        container_drawn_w = dim1_max * scale
        container_drawn_h = dim2_max * scale
        
        # Centering the visualization within the view pane
        x_offset += (vp_w - container_drawn_w) / 2
        y_offset += (vp_h - container_drawn_h) / 2
        
        cont_x1 = x_offset
        cont_y1 = y_offset
        cont_x2 = x_offset + container_drawn_w
        cont_y2 = y_offset + container_drawn_h

        # Draw Container Outline
        self.viz_canvas.create_rectangle(
            cont_x1, cont_y1, cont_x2, cont_y2, outline="black", width=2
        )
        
        # Draw Container Measurements (Blue text)
        self.viz_canvas.create_text(cont_x1 + container_drawn_w / 2, cont_y2 + measure_offset_h - 10,
                                    text=f"{dim1_max} mm", font=("TkDefaultFont", 10, "bold"), fill="#0056B3")
        
        self.viz_canvas.create_text(cont_x1 - measure_offset_v + 10, cont_y1 + container_drawn_h / 2,
                                    text=f"{dim2_max} mm", font=("TkDefaultFont", 10, "bold"), anchor='e', fill="#0056B3")

        # Draw Boxes
        for i, p_box in enumerate(boxes):
            d1 = getattr(p_box, d1_attr)
            d2 = getattr(p_box, d2_attr)
            l1 = getattr(p_box, l1_attr)
            l2 = getattr(p_box, l2_attr)
            
            x1 = cont_x1 + d1 * scale
            x2 = cont_x1 + (d1 + l1) * scale
            
            # Vertical dimension handling (Z axis needs flipping, Y does not for Top View)
            if flip_v:
                y1 = cont_y1 + (dim2_max - (d2 + l2)) * scale 
                y2 = cont_y1 + (dim2_max - d2) * scale
            else:
                y1 = cont_y1 + d2 * scale
                y2 = cont_y1 + (d2 + l2) * scale
            
            # Draw Box Rectangle
            color = p_box.box.color_hex
            self.viz_canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="black")
            
            # Draw box name
            self.viz_canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2 - 8, # Nudge text up slightly
                text=p_box.box.name, 
                fill="black",
                font=("TkDefaultFont", 9, "bold")
            )
            
            # Draw box dimensions (L x H or W x H) only for Front and Side views (where draw_box_dims is True)
            if draw_box_dims:
                dims_text = f"{l1}x{l2}"
                self.viz_canvas.create_text(
                    (x1 + x2) / 2, (y1 + y2) / 2 + 8, # Nudge text down slightly
                    text=dims_text, 
                    fill="black",
                    font=("TkDefaultFont", 8)
                )

# --- Run the app ---
if __name__ == "__main__":
    app = PackerApp()
    app.mainloop()