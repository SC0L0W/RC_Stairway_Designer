import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math
from dataclasses import dataclass
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.enums import TA_CENTER
from datetime import datetime

# Try to import ezdxf for DXF export
try:
    import ezdxf
    from ezdxf import colors as dxf_colors
    from ezdxf.enums import TextEntityAlignment

    DXF_AVAILABLE = True
except ImportError:
    DXF_AVAILABLE = False


# Data classes
@dataclass
class MaterialProperties:
    fc: float
    fy: float
    concrete_unit_weight: float
    beta1: float

    def __post_init__(self):
        self.rho_b = (0.85 * self.fc * self.beta1 * 600) / (self.fy * (self.fy + 600))
        self.rho_max = 0.75 * self.rho_b
        self.rho_min = 1.4 / self.fy


@dataclass
class GeometricProperties:
    tread_width: float
    riser_height: float
    clear_span: float
    steps_first_flight: int
    steps_second_flight: int


@dataclass
class LoadProperties:
    live_load: float
    misc_live_load: float
    floor_finish: float
    misc_dead_load: float


@dataclass
class DesignParameters:
    cover: float
    main_bar_diameter: float
    temp_bar_diameter: float
    hook_bar_diameter: float


# DXF Generator Class
class StairwayDXFGenerator:
    """Generates detailed DXF drawings for concrete stairways"""

    def __init__(self, design_results, geometry, materials, design_params):
        self.results = design_results
        self.geometry = geometry
        self.materials = materials
        self.design_params = design_params

        # Layer definitions
        self.layers = {
            'CONCRETE': {'color': dxf_colors.WHITE, 'lineweight': 35},
            'REINFORCEMENT': {'color': dxf_colors.RED, 'lineweight': 25},
            'DIMENSIONS': {'color': dxf_colors.CYAN, 'lineweight': 18},
            'TEXT': {'color': dxf_colors.YELLOW, 'lineweight': 18},
            'CENTERLINE': {'color': dxf_colors.GREEN, 'lineweight': 13},
            'HATCHING': {'color': dxf_colors.GRAY, 'lineweight': 13},
        }

    def create_dxf(self, filename):
        """Create complete DXF drawing with all views"""
        self.doc = ezdxf.new('R2010')
        self.msp = self.doc.modelspace()

        # Setup layers
        self._setup_layers()

        # Create views for each flight
        y_offset = 0
        for key in self.results:
            flight_data = self.results[key]
            flight_name = flight_data['flight_name']

            # Draw section view
            self._draw_section_view(flight_data, x_offset=0, y_offset=y_offset)

            # Draw plan view
            self._draw_plan_view(flight_data, x_offset=8000, y_offset=y_offset)

            # Draw reinforcement detail
            self._draw_reinforcement_detail(flight_data, x_offset=0, y_offset=y_offset - 4000)

            # Add title block
            self._add_title_block(flight_name, x_offset=12000, y_offset=y_offset)

            # Offset for next flight
            y_offset -= 8000

        # Save DXF file
        self.doc.saveas(filename)
        return True

    def _setup_layers(self):
        """Setup drawing layers"""
        for layer_name, props in self.layers.items():
            layer = self.doc.layers.add(layer_name)
            layer.color = props['color']
            if 'lineweight' in props:
                layer.lineweight = props['lineweight']

    def _draw_section_view(self, flight_data, x_offset=0, y_offset=0):
        """Draw longitudinal section of stairway"""
        tread = self.geometry.tread_width * 1000  # Convert to mm
        riser = self.geometry.riser_height * 1000
        thickness = flight_data['slab_thickness']

        # Calculate number of steps
        num_steps = self.geometry.steps_first_flight if 'First' in flight_data[
            'flight_name'] else self.geometry.steps_second_flight

        x_start = x_offset
        y_start = y_offset

        # Draw title
        self.msp.add_text(
            f"SECTION VIEW - {flight_data['flight_name'].upper()}",
            dxfattribs={'layer': 'TEXT', 'height': 150}
        ).set_placement((x_start, y_start + 500), align=TextEntityAlignment.BOTTOM_LEFT)

        # Draw slab outline with steps
        points = [(x_start, y_start)]

        # Draw each step
        for i in range(num_steps):
            points.append((x_start + (i + 1) * tread, y_start + i * riser))
            points.append((x_start + (i + 1) * tread, y_start + (i + 1) * riser))

        # Calculate slab bottom
        total_run = num_steps * tread
        total_rise = num_steps * riser
        angle = math.atan2(total_rise, total_run)

        slab_thickness_perpendicular = thickness / math.cos(angle)
        dx_bottom = -slab_thickness_perpendicular * math.sin(angle)
        dy_bottom = -slab_thickness_perpendicular * math.cos(angle)

        points.append((points[-1][0] + dx_bottom, points[-1][1] + dy_bottom))
        points.append((x_start + dx_bottom, y_start + dy_bottom))
        points.append((x_start, y_start))

        # Draw concrete outline
        self.msp.add_lwpolyline(points, dxfattribs={'layer': 'CONCRETE', 'closed': True})

        # Add concrete hatch
        hatch = self.msp.add_hatch(color=dxf_colors.GRAY)
        hatch.set_pattern_fill('ANSI31', scale=50)
        hatch.paths.add_polyline_path(points)
        hatch.dxf.layer = 'HATCHING'

        # Draw reinforcement
        self._draw_main_reinforcement_section(flight_data, x_start, y_start, num_steps,
                                              tread, riser, thickness, angle)

        # Add dimensions
        self._add_section_dimensions(x_start, y_start, num_steps, tread, riser, thickness, total_run, total_rise)

    def _draw_main_reinforcement_section(self, flight_data, x_start, y_start, num_steps,
                                         tread, riser, thickness, angle):
        """Draw main reinforcement bars in section view"""
        cover = self.design_params.cover
        bar_diameter = self.design_params.main_bar_diameter
        spacing = flight_data['main_bar_spacing']

        total_run = num_steps * tread
        num_bars = int(total_run / spacing) + 1

        for i in range(num_bars):
            x_pos = x_start + (i * spacing)

            if x_pos > x_start + total_run:
                break

            step_num = int(x_pos / tread)
            if step_num >= num_steps:
                step_num = num_steps - 1

            y_pos = y_start + step_num * riser

            offset_perpendicular = cover + bar_diameter / 2
            dx_offset = -offset_perpendicular * math.sin(angle)
            dy_offset = -offset_perpendicular * math.cos(angle)

            # Draw bar as circle
            self.msp.add_circle(
                (x_pos + dx_offset, y_pos + dy_offset),
                radius=bar_diameter / 2,
                dxfattribs={'layer': 'REINFORCEMENT'}
            )

    def _draw_plan_view(self, flight_data, x_offset=0, y_offset=0):
        """Draw plan view of stairway"""
        tread = self.geometry.tread_width * 1000
        num_steps = self.geometry.steps_first_flight if 'First' in flight_data[
            'flight_name'] else self.geometry.steps_second_flight

        stair_width = 1200  # mm

        x_start = x_offset
        y_start = y_offset

        # Draw title
        self.msp.add_text(
            f"PLAN VIEW - {flight_data['flight_name'].upper()}",
            dxfattribs={'layer': 'TEXT', 'height': 150}
        ).set_placement((x_start, y_start + 500), align=TextEntityAlignment.BOTTOM_LEFT)

        total_length = num_steps * tread

        # Outer rectangle
        self.msp.add_lwpolyline([
            (x_start, y_start),
            (x_start + total_length, y_start),
            (x_start + total_length, y_start - stair_width),
            (x_start, y_start - stair_width),
            (x_start, y_start)
        ], dxfattribs={'layer': 'CONCRETE'})

        # Draw tread lines
        for i in range(1, num_steps):
            x_pos = x_start + i * tread
            self.msp.add_line(
                (x_pos, y_start),
                (x_pos, y_start - stair_width),
                dxfattribs={'layer': 'CONCRETE'}
            )

        # Draw main reinforcement
        spacing = flight_data['main_bar_spacing']
        num_bars = int(stair_width / spacing) + 1

        for i in range(num_bars):
            y_pos = y_start - (i * spacing)
            if y_pos < y_start - stair_width:
                break

            self.msp.add_line(
                (x_start, y_pos),
                (x_start + total_length, y_pos),
                dxfattribs={'layer': 'REINFORCEMENT', 'linetype': 'DASHED'}
            )

        # Add dimensions
        self._add_plan_dimensions(x_start, y_start, total_length, stair_width)

    def _draw_reinforcement_detail(self, flight_data, x_offset=0, y_offset=0):
        """Draw detailed reinforcement schedule"""
        x_start = x_offset
        y_start = y_offset

        # Title
        self.msp.add_text(
            "REINFORCEMENT DETAILS",
            dxfattribs={'layer': 'TEXT', 'height': 150}
        ).set_placement((x_start, y_start + 500), align=TextEntityAlignment.BOTTOM_LEFT)

        # Detail box
        box_width = 3500
        box_height = 2000

        self.msp.add_lwpolyline([
            (x_start, y_start),
            (x_start + box_width, y_start),
            (x_start + box_width, y_start - box_height),
            (x_start, y_start - box_height),
            (x_start, y_start)
        ], dxfattribs={'layer': 'CONCRETE'})

        # Add text details
        y_text = y_start - 200
        line_height = 180

        main_dia = int(self.design_params.main_bar_diameter)
        temp_dia = int(self.design_params.temp_bar_diameter)
        main_spacing = int(flight_data['main_bar_spacing'])
        temp_spacing = int(flight_data['temp_bar_spacing'])

        details = [
            f"MAIN REINFORCEMENT:",
            f"  {main_dia}mm dia @ {main_spacing}mm c/c",
            f"  As required = {flight_data['main_steel_area']:.0f} mm2/m",
            "",
            f"TEMPERATURE REINFORCEMENT:",
            f"  {temp_dia}mm dia @ {temp_spacing}mm c/c",
            f"  As provided = {flight_data['temp_steel_area']:.0f} mm2/m",
            "",
            f"CONCRETE COVER: {int(self.design_params.cover)}mm",
            f"SLAB THICKNESS: {int(flight_data['slab_thickness'])}mm",
            f"EFFECTIVE DEPTH: {int(flight_data['effective_depth'])}mm"
        ]

        for detail in details:
            self.msp.add_text(
                detail,
                dxfattribs={'layer': 'TEXT', 'height': 100}
            ).set_placement((x_start + 100, y_text), align=TextEntityAlignment.BOTTOM_LEFT)
            y_text -= line_height

        # Draw rebar symbols
        self._draw_rebar_symbols(x_start + 2200, y_start - 500, main_dia, temp_dia)

    def _draw_rebar_symbols(self, x_start, y_start, main_dia, temp_dia):
        """Draw reinforcement bar symbols"""
        # Main bar
        self.msp.add_circle(
            (x_start, y_start),
            radius=main_dia / 2,
            dxfattribs={'layer': 'REINFORCEMENT'}
        )

        self.msp.add_text(
            f"Main Bar {main_dia}mm",
            dxfattribs={'layer': 'TEXT', 'height': 80}
        ).set_placement((x_start + 50, y_start), align=TextEntityAlignment.MIDDLE_LEFT)

        # Temperature bar
        self.msp.add_circle(
            (x_start, y_start - 400),
            radius=temp_dia / 2,
            dxfattribs={'layer': 'REINFORCEMENT'}
        )

        self.msp.add_text(
            f"Temp Bar {temp_dia}mm",
            dxfattribs={'layer': 'TEXT', 'height': 80}
        ).set_placement((x_start + 50, y_start - 400), align=TextEntityAlignment.MIDDLE_LEFT)

    def _add_section_dimensions(self, x_start, y_start, num_steps, tread, riser, thickness, total_run, total_rise):
        """Add dimensions to section view"""
        # Total run dimension
        y_dim = y_start - 500

        self.msp.add_line(
            (x_start, y_dim),
            (x_start + total_run, y_dim),
            dxfattribs={'layer': 'DIMENSIONS'}
        )

        self.msp.add_text(
            f"TOTAL RUN: {int(total_run)}mm ({num_steps} x {int(tread)}mm)",
            dxfattribs={'layer': 'DIMENSIONS', 'height': 100}
        ).set_placement((x_start + total_run / 2, y_dim - 150), align=TextEntityAlignment.TOP_CENTER)

        # Total rise dimension
        x_dim = x_start + total_run + 500

        self.msp.add_line(
            (x_dim, y_start),
            (x_dim, y_start + total_rise),
            dxfattribs={'layer': 'DIMENSIONS'}
        )

        self.msp.add_text(
            f"RISE: {int(total_rise)}mm",
            dxfattribs={'layer': 'DIMENSIONS', 'height': 100, 'rotation': 90}
        ).set_placement((x_dim + 150, y_start + total_rise / 2), align=TextEntityAlignment.BOTTOM_CENTER)

        # Thickness
        self.msp.add_text(
            f"t={int(thickness)}mm",
            dxfattribs={'layer': 'DIMENSIONS', 'height': 100}
        ).set_placement((x_start - 300, y_start - thickness / 2), align=TextEntityAlignment.MIDDLE_RIGHT)

    def _add_plan_dimensions(self, x_start, y_start, total_length, stair_width):
        """Add dimensions to plan view"""
        # Length dimension
        y_dim = y_start - stair_width - 300

        self.msp.add_line(
            (x_start, y_dim),
            (x_start + total_length, y_dim),
            dxfattribs={'layer': 'DIMENSIONS'}
        )

        self.msp.add_text(
            f"LENGTH: {int(total_length)}mm",
            dxfattribs={'layer': 'DIMENSIONS', 'height': 100}
        ).set_placement((x_start + total_length / 2, y_dim - 150), align=TextEntityAlignment.TOP_CENTER)

        # Width dimension
        x_dim = x_start - 300

        self.msp.add_line(
            (x_dim, y_start),
            (x_dim, y_start - stair_width),
            dxfattribs={'layer': 'DIMENSIONS'}
        )

        self.msp.add_text(
            f"WIDTH: {int(stair_width)}mm",
            dxfattribs={'layer': 'DIMENSIONS', 'height': 100, 'rotation': 90}
        ).set_placement((x_dim - 150, y_start - stair_width / 2), align=TextEntityAlignment.BOTTOM_CENTER)

    def _add_title_block(self, flight_name, x_offset=0, y_offset=0):
        """Add title block with project information"""
        x_start = x_offset
        y_start = y_offset

        box_width = 3500
        box_height = 1500

        # Border
        self.msp.add_lwpolyline([
            (x_start, y_start),
            (x_start + box_width, y_start),
            (x_start + box_width, y_start - box_height),
            (x_start, y_start - box_height),
            (x_start, y_start)
        ], dxfattribs={'layer': 'TEXT'})

        # Information
        y_text = y_start - 200
        line_height = 200

        date_str = datetime.now().strftime("%B %d, %Y")

        info_lines = [
            "CONCRETE STAIRWAY DESIGN",
            f"FLIGHT: {flight_name}",
            "",
            f"CODE: NSCP 2015",
            f"DATE: {date_str}",
            "",
            f"f'c = {self.materials.fc} MPa",
            f"fy = {self.materials.fy} MPa"
        ]

        for line in info_lines:
            self.msp.add_text(
                line,
                dxfattribs={'layer': 'TEXT', 'height': 120 if line == info_lines[0] else 100}
            ).set_placement((x_start + 100, y_text), align=TextEntityAlignment.BOTTOM_LEFT)
            y_text -= line_height


class ModernStairwayDesigner:
    def __init__(self, root):
        self.root = root
        self.root.title("NSCP 2015 Stairway Designer Pro")
        self.root.geometry("1400x800")

        # Modern color scheme
        self.colors = {
            'primary': '#2C3E50',
            'secondary': '#3498DB',
            'accent': '#E74C3C',
            'success': '#27AE60',
            'warning': '#F39C12',
            'bg_light': '#ECF0F1',
            'bg_dark': '#34495E',
            'text_light': '#FFFFFF',
            'card_bg': '#FFFFFF'
        }

        self.root.configure(bg=self.colors['bg_light'])

        # Support options
        self.support_options = [
            "Two-point support with stringers",
            "One-end supported (cantilever)",
            "Open support (floating)"
        ]

        # Default data
        self.geometry = None
        self.loads = None
        self.design_params = None
        self.materials = None
        self.results = {}

        # Configure styles
        self.configure_styles()

        # Setup UI
        self.setup_modern_ui()

    def configure_styles(self):
        """Configure modern ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')

        # Configure frame styles
        style.configure('Card.TFrame', background=self.colors['card_bg'], relief='flat')
        style.configure('Header.TFrame', background=self.colors['primary'])

        # Configure label styles
        style.configure('Title.TLabel',
                        background=self.colors['primary'],
                        foreground=self.colors['text_light'],
                        font=('Segoe UI', 24, 'bold'))
        style.configure('Subtitle.TLabel',
                        background=self.colors['primary'],
                        foreground=self.colors['text_light'],
                        font=('Segoe UI', 10))
        style.configure('CardTitle.TLabel',
                        background=self.colors['card_bg'],
                        foreground=self.colors['primary'],
                        font=('Segoe UI', 12, 'bold'))
        style.configure('CardLabel.TLabel',
                        background=self.colors['card_bg'],
                        foreground=self.colors['primary'],
                        font=('Segoe UI', 10))

        # Configure button styles
        style.configure('Primary.TButton',
                        background=self.colors['secondary'],
                        foreground=self.colors['text_light'],
                        borderwidth=0,
                        font=('Segoe UI', 10, 'bold'),
                        padding=10)
        style.map('Primary.TButton',
                  background=[('active', '#2980B9')])

        style.configure('Success.TButton',
                        background=self.colors['success'],
                        foreground=self.colors['text_light'],
                        borderwidth=0,
                        font=('Segoe UI', 10, 'bold'),
                        padding=10)

        style.configure('Warning.TButton',
                        background=self.colors['warning'],
                        foreground=self.colors['text_light'],
                        borderwidth=0,
                        font=('Segoe UI', 10, 'bold'),
                        padding=10)

        style.configure('Danger.TButton',
                        background=self.colors['accent'],
                        foreground=self.colors['text_light'],
                        borderwidth=0,
                        font=('Segoe UI', 10, 'bold'),
                        padding=10)

    def setup_modern_ui(self):
        """Setup modern UI layout"""
        # Header
        header_frame = ttk.Frame(self.root, style='Header.TFrame', height=100)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)

        ttk.Label(header_frame, text="🏗️ Stairway Designer Pro",
                  style='Title.TLabel').pack(pady=(20, 5))
        ttk.Label(header_frame, text="NSCP 2015 Compliant Concrete Stairway Design Tool",
                  style='Subtitle.TLabel').pack()

        # Main container
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Left panel (inputs) - 60% width
        left_panel = ttk.Frame(main_container)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Canvas for scrolling
        canvas = tk.Canvas(left_panel, bg=self.colors['bg_light'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Input sections
        self.create_material_card()
        self.create_rebar_card()
        self.create_loads_card()
        self.create_geometry_card()
        self.create_support_card()
        self.create_thickness_card()
        self.create_options_card()
        self.create_action_buttons()

        # Right panel (results) - 40% width
        right_panel = ttk.Frame(main_container, style='Card.TFrame')
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Results header
        results_header = ttk.Frame(right_panel, style='Card.TFrame')
        results_header.pack(fill=tk.X, padx=15, pady=(15, 10))

        ttk.Label(results_header, text="📊 Design Results",
                  style='CardTitle.TLabel').pack(anchor=tk.W)

        # Results text area
        results_container = ttk.Frame(right_panel, style='Card.TFrame')
        results_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        self.results_text = tk.Text(results_container,
                                    wrap=tk.WORD,
                                    font=('Consolas', 9),
                                    bg='#FAFAFA',
                                    fg=self.colors['primary'],
                                    relief='flat',
                                    padx=10,
                                    pady=10)
        results_scrollbar = ttk.Scrollbar(results_container, orient="vertical",
                                          command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scrollbar.set)
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        results_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def create_card(self, title, icon=""):
        """Create a modern card container"""
        card = ttk.Frame(self.scrollable_frame, style='Card.TFrame', relief='raised', borderwidth=1)
        card.pack(fill=tk.X, pady=(0, 15), padx=5)

        header = ttk.Frame(card, style='Card.TFrame')
        header.pack(fill=tk.X, padx=15, pady=(15, 10))

        ttk.Label(header, text=f"{icon} {title}", style='CardTitle.TLabel').pack(anchor=tk.W)

        separator = ttk.Separator(card, orient='horizontal')
        separator.pack(fill=tk.X, padx=15)

        content = ttk.Frame(card, style='Card.TFrame')
        content.pack(fill=tk.X, padx=15, pady=15)

        return content

    def create_labeled_entry(self, parent, label, variable, row, col, units=""):
        """Create a labeled entry with modern styling"""
        ttk.Label(parent, text=label, style='CardLabel.TLabel').grid(
            row=row, column=col * 2, sticky=tk.W, padx=(0, 5), pady=5)

        entry_frame = ttk.Frame(parent, style='Card.TFrame')
        entry_frame.grid(row=row, column=col * 2 + 1, sticky=tk.W, padx=(0, 15), pady=5)

        entry = ttk.Entry(entry_frame, textvariable=variable, width=12)
        entry.pack(side=tk.LEFT)

        if units:
            ttk.Label(entry_frame, text=units, style='CardLabel.TLabel').pack(
                side=tk.LEFT, padx=(5, 0))

    def create_material_card(self):
        content = self.create_card("Material Properties", "🧱")

        self.fc_var = tk.StringVar(value="20.7")
        self.fy_var = tk.StringVar(value="275")
        self.gamma_var = tk.StringVar(value="24")
        self.beta1_var = tk.StringVar(value="0.85")

        self.create_labeled_entry(content, "f'c:", self.fc_var, 0, 0, "MPa")
        self.create_labeled_entry(content, "fy:", self.fy_var, 0, 1, "MPa")
        self.create_labeled_entry(content, "γ:", self.gamma_var, 1, 0, "kN/m³")
        self.create_labeled_entry(content, "β₁:", self.beta1_var, 1, 1)

    def create_rebar_card(self):
        content = self.create_card("Reinforcement Bars", "⚙️")

        self.main_bar_var = tk.StringVar(value="12")
        self.temp_bar_var = tk.StringVar(value="10")
        self.hook_bar_var = tk.StringVar(value="10")
        self.cover_var = tk.StringVar(value="20")

        self.create_labeled_entry(content, "Main Bar:", self.main_bar_var, 0, 0, "mm")
        self.create_labeled_entry(content, "Temp Bar:", self.temp_bar_var, 0, 1, "mm")
        self.create_labeled_entry(content, "Hook Bar:", self.hook_bar_var, 1, 0, "mm")
        self.create_labeled_entry(content, "Cover:", self.cover_var, 1, 1, "mm")

    def create_loads_card(self):
        content = self.create_card("Service Loads", "📦")

        self.live_load_var = tk.StringVar(value="1.9")
        self.misc_live_var = tk.StringVar(value="0.5")
        self.floor_finish_var = tk.StringVar(value="1.0")
        self.misc_dead_var = tk.StringVar(value="0.5")

        self.create_labeled_entry(content, "Live Load:", self.live_load_var, 0, 0, "kPa")
        self.create_labeled_entry(content, "Misc. Live:", self.misc_live_var, 0, 1, "kPa")
        self.create_labeled_entry(content, "Floor Finish:", self.floor_finish_var, 1, 0, "kPa")
        self.create_labeled_entry(content, "Misc. Dead:", self.misc_dead_var, 1, 1, "kPa")

    def create_geometry_card(self):
        content = self.create_card("Geometry", "📐")

        self.tread_var = tk.StringVar(value="0.25")
        self.riser_var = tk.StringVar(value="0.175")
        self.clear_span_var = tk.StringVar(value="3.0")
        self.steps1_var = tk.StringVar(value="8")
        self.steps2_var = tk.StringVar(value="8")

        self.create_labeled_entry(content, "Tread Width:", self.tread_var, 0, 0, "m")
        self.create_labeled_entry(content, "Riser Height:", self.riser_var, 0, 1, "m")
        self.create_labeled_entry(content, "Clear Span:", self.clear_span_var, 1, 0, "m")
        self.create_labeled_entry(content, "Steps (1st):", self.steps1_var, 2, 0)
        self.create_labeled_entry(content, "Steps (2nd):", self.steps2_var, 2, 1)

    def create_support_card(self):
        content = self.create_card("Support Configuration", "🔧")

        self.support1_var = tk.StringVar(value=self.support_options[0])
        self.support2_var = tk.StringVar(value=self.support_options[0])

        ttk.Label(content, text="First Flight:", style='CardLabel.TLabel').grid(
            row=0, column=0, sticky=tk.W, pady=5)
        ttk.Combobox(content, textvariable=self.support1_var, values=self.support_options,
                     width=35, state="readonly").grid(row=0, column=1, pady=5, sticky=tk.W)

        ttk.Label(content, text="Second Flight:", style='CardLabel.TLabel').grid(
            row=1, column=0, sticky=tk.W, pady=5)
        ttk.Combobox(content, textvariable=self.support2_var, values=self.support_options,
                     width=35, state="readonly").grid(row=1, column=1, pady=5, sticky=tk.W)

    def create_thickness_card(self):
        content = self.create_card("Slab Thickness", "📏")

        self.use_proposed_var = tk.BooleanVar()
        self.thickness_var = tk.StringVar(value="150")

        ttk.Checkbutton(content, text="Use Proposed Thickness",
                        variable=self.use_proposed_var).grid(row=0, column=0, columnspan=2,
                                                             sticky=tk.W, pady=5)
        self.create_labeled_entry(content, "Proposed:", self.thickness_var, 1, 0, "mm")

    def create_options_card(self):
        content = self.create_card("Design Options", "⚡")

        self.single_flight_var = tk.BooleanVar()
        ttk.Checkbutton(content, text="Design Only First Flight",
                        variable=self.single_flight_var).pack(anchor=tk.W, pady=5)

    def create_action_buttons(self):
        button_frame = ttk.Frame(self.scrollable_frame)
        button_frame.pack(fill=tk.X, pady=20, padx=5)

        ttk.Button(button_frame, text="🚀 Calculate Design",
                   command=self.calculate_design,
                   style='Primary.TButton').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        ttk.Button(button_frame, text="📄 Generate PDF",
                   command=self.generate_report,
                   style='Success.TButton').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        ttk.Button(button_frame, text="📐 Export DXF",
                   command=self.export_dxf,
                   style='Warning.TButton').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        ttk.Button(button_frame, text="🗑️ Clear",
                   command=self.clear_results,
                   style='Danger.TButton').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

    # Calculation methods
    def get_support_factor(self, support_config: str) -> float:
        factors = {
            "Two-point support with stringers": 8,
            "One-end supported (cantilever)": 2,
            "Open support (floating)": 10
        }
        return factors.get(support_config, 8)

    def calculate_minimum_thickness(self, support_config: str) -> float:
        if "cantilever" in support_config.lower():
            h_min = (self.geometry.clear_span * 1000) / 10
        else:
            h_min = (self.geometry.clear_span * 1000) / 20
        return h_min

    def calculate_dead_loads(self, slab_thickness):
        h = slab_thickness / 1000
        weight_steps = 0.5 * self.geometry.riser_height * self.materials.concrete_unit_weight
        R = self.geometry.riser_height
        T = self.geometry.tread_width
        slope_factor = math.sqrt(R ** 2 + T ** 2) / T
        weight_slab = h * self.materials.concrete_unit_weight * slope_factor
        DL1 = weight_steps + weight_slab
        DL2 = self.loads.floor_finish + self.loads.misc_dead_load
        total_DL = DL1 + DL2
        return {'weight_steps': weight_steps, 'weight_slab': weight_slab, 'self_weight': DL1,
                'additional_DL': DL2, 'total_DL': total_DL}

    def calculate_live_loads(self):
        return self.loads.live_load + self.loads.misc_live_load

    def calculate_factored_load(self, dead_load, live_load):
        return 1.2 * dead_load + 1.6 * live_load

    def calculate_effective_depth(self, slab_thickness):
        return slab_thickness - self.design_params.cover - self.design_params.main_bar_diameter / 2

    def calculate_maximum_moment(self, factored_load, support_config):
        Lc = self.geometry.clear_span
        factor = self.get_support_factor(support_config)
        return factored_load * Lc ** 2 / factor

    def calculate_required_steel_area(self, moment, effective_depth):
        d = effective_depth / 1000
        Mu = moment * 1000
        phi = 0.9
        b = 1.0
        fc = self.materials.fc * 1e6
        fy = self.materials.fy * 1e6
        a_assumed = 0.1 * d
        As_required = Mu / (phi * fy * (d - a_assumed / 2))
        a_actual = As_required * fy / (0.85 * fc * b)
        if abs(a_actual - a_assumed) > 0.001:
            As_required = Mu / (phi * fy * (d - a_actual / 2))
        rho = As_required / (b * d)
        return As_required * 1e6, rho

    def check_steel_ratio_limits(self, rho):
        if rho < self.materials.rho_min:
            return False, self.materials.rho_min
        elif rho > self.materials.rho_max:
            return False, self.materials.rho_max
        else:
            return True, rho

    def calculate_bar_spacing(self, As_required, bar_diameter):
        Ab = math.pi * (bar_diameter / 2) ** 2
        spacing = Ab / (As_required / 1000)
        return spacing

    def calculate_temperature_reinforcement(self, slab_thickness):
        b = 1000
        h = slab_thickness
        As_temp = 0.0018 * b * h
        Ab_temp = math.pi * (self.design_params.temp_bar_diameter / 2) ** 2
        spacing_temp = Ab_temp / (As_temp / 1000)
        max_spacing = min(5 * h, 450)
        return As_temp, min(spacing_temp, max_spacing)

    def design_flight(self, flight_name, support_config, proposed_thickness=None):
        h_min = self.calculate_minimum_thickness(support_config)
        if proposed_thickness is None:
            slab_thickness = max(h_min + 20, 150)
        else:
            slab_thickness = max(proposed_thickness, h_min)
        dead_loads = self.calculate_dead_loads(slab_thickness)
        live_load = self.calculate_live_loads()
        factored_load = self.calculate_factored_load(dead_loads['total_DL'], live_load)
        effective_depth = self.calculate_effective_depth(slab_thickness)
        max_moment = self.calculate_maximum_moment(factored_load, support_config)
        As_required, rho = self.calculate_required_steel_area(max_moment, effective_depth)
        is_ok, governing_rho = self.check_steel_ratio_limits(rho)
        if not is_ok:
            As_required = governing_rho * 1000 * effective_depth
        main_spacing = self.calculate_bar_spacing(As_required, self.design_params.main_bar_diameter)
        max_main_spacing = 3 * slab_thickness
        final_main_spacing = min(main_spacing, max_main_spacing)
        As_temp, temp_spacing = self.calculate_temperature_reinforcement(slab_thickness)
        return {
            'flight_name': flight_name,
            'support_config': support_config,
            'h_min': h_min,
            'slab_thickness': slab_thickness,
            'effective_depth': effective_depth,
            'dead_load': dead_loads['total_DL'],
            'live_load': live_load,
            'factored_load': factored_load,
            'max_moment': max_moment,
            'main_steel_area': As_required,
            'main_bar_spacing': final_main_spacing,
            'temp_steel_area': As_temp,
            'temp_bar_spacing': temp_spacing,
            'steel_ratio': governing_rho
        }

    def calculate_design(self):
        try:
            self.materials = MaterialProperties(
                fc=float(self.fc_var.get()),
                fy=float(self.fy_var.get()),
                concrete_unit_weight=float(self.gamma_var.get()),
                beta1=float(self.beta1_var.get())
            )
            self.geometry = GeometricProperties(
                tread_width=float(self.tread_var.get()),
                riser_height=float(self.riser_var.get()),
                clear_span=float(self.clear_span_var.get()),
                steps_first_flight=int(self.steps1_var.get()),
                steps_second_flight=int(self.steps2_var.get())
            )
            self.loads = LoadProperties(
                live_load=float(self.live_load_var.get()),
                misc_live_load=float(self.misc_live_var.get()),
                floor_finish=float(self.floor_finish_var.get()),
                misc_dead_load=float(self.misc_dead_var.get())
            )
            self.design_params = DesignParameters(
                cover=float(self.cover_var.get()),
                main_bar_diameter=float(self.main_bar_var.get()),
                temp_bar_diameter=float(self.temp_bar_var.get()),
                hook_bar_diameter=float(self.hook_bar_var.get())
            )
            proposed_thickness = float(self.thickness_var.get()) if self.use_proposed_var.get() else None

            if self.single_flight_var.get():
                self.results = {
                    'flight1': self.design_flight('First Flight', self.support1_var.get(), proposed_thickness),
                }
            else:
                self.results = {
                    'flight1': self.design_flight('First Flight', self.support1_var.get(), proposed_thickness),
                    'flight2': self.design_flight('Second Flight', self.support2_var.get(), proposed_thickness),
                }
            self.display_results()
            messagebox.showinfo("✅ Success", "Design calculation completed successfully!")
        except ValueError as e:
            messagebox.showerror("❌ Input Error", f"Check your inputs:\n{str(e)}")
        except Exception as e:
            messagebox.showerror("❌ Error", f"Error during calculation:\n{str(e)}")

    def display_results(self):
        self.results_text.delete(1.0, tk.END)
        if not self.results:
            return

        txt = "=" * 70 + "\n"
        txt += "  NSCP 2015 CONCRETE STAIRWAY DESIGN RESULTS\n"
        txt += "=" * 70 + "\n\n"

        m = self.materials
        txt += "📋 MATERIAL PROPERTIES\n"
        txt += "-" * 70 + "\n"
        txt += f"  Concrete Strength (f'c)    : {m.fc} MPa\n"
        txt += f"  Steel Yield Strength (fy)  : {m.fy} MPa\n"
        txt += f"  Concrete Unit Weight (γ)   : {m.concrete_unit_weight} kN/m³\n"
        txt += f"  Beta Factor (β₁)           : {m.beta1}\n"
        txt += f"  Min Steel Ratio (ρ_min)    : {m.rho_min:.6f}\n"
        txt += f"  Max Steel Ratio (ρ_max)    : {m.rho_max:.6f}\n\n"

        g = self.geometry
        txt += "📐 GEOMETRY\n"
        txt += "-" * 70 + "\n"
        txt += f"  Tread Width                : {g.tread_width} m\n"
        txt += f"  Riser Height               : {g.riser_height} m\n"
        txt += f"  Clear Span                 : {g.clear_span} m\n"
        txt += f"  Steps (First Flight)       : {g.steps_first_flight}\n"
        txt += f"  Steps (Second Flight)      : {g.steps_second_flight}\n\n"

        l = self.loads
        txt += "📦 LOADING\n"
        txt += "-" * 70 + "\n"
        txt += f"  Live Load                  : {l.live_load} kPa\n"
        txt += f"  Misc. Live Load            : {l.misc_live_load} kPa\n"
        txt += f"  Floor Finish               : {l.floor_finish} kPa\n"
        txt += f"  Misc. Dead Load            : {l.misc_dead_load} kPa\n\n"

        for key in self.results:
            f = self.results[key]
            txt += "=" * 70 + "\n"
            txt += f"  {f['flight_name'].upper()} - DESIGN SUMMARY\n"
            txt += "=" * 70 + "\n\n"

            txt += f"🔧 Support Configuration    : {f['support_config']}\n\n"

            txt += "SLAB DIMENSIONS\n"
            txt += "-" * 70 + "\n"
            txt += f"  Minimum Thickness          : {f['h_min']:.1f} mm\n"
            txt += f"  Adopted Thickness          : {f['slab_thickness']:.1f} mm\n"
            txt += f"  Effective Depth            : {f['effective_depth']:.1f} mm\n\n"

            txt += "LOAD ANALYSIS\n"
            txt += "-" * 70 + "\n"
            txt += f"  Dead Load (DL)             : {f['dead_load']:.2f} kPa\n"
            txt += f"  Live Load (LL)             : {f['live_load']:.2f} kPa\n"
            txt += f"  Factored Load (1.2DL+1.6LL): {f['factored_load']:.2f} kPa\n\n"

            txt += "MOMENT & REINFORCEMENT\n"
            txt += "-" * 70 + "\n"
            txt += f"  Maximum Moment             : {f['max_moment']:.2f} kN·m\n"
            txt += f"  Required Steel Area        : {f['main_steel_area']:.2f} mm²/m\n"
            txt += f"  Steel Ratio (ρ)            : {f['steel_ratio']:.6f}\n\n"

            txt += "REINFORCEMENT SCHEDULE\n"
            txt += "-" * 70 + "\n"
            main_dia = int(self.design_params.main_bar_diameter)
            temp_dia = int(self.design_params.temp_bar_diameter)
            txt += f"  Main Bars                  : {main_dia}mm ⌀ @ {f['main_bar_spacing']:.0f}mm c/c\n"
            txt += f"  Temperature Bars           : {temp_dia}mm ⌀ @ {f['temp_bar_spacing']:.0f}mm c/c\n\n"

        txt += "=" * 70 + "\n"
        txt += "  ✅ DESIGN COMPLETE - All requirements satisfied per NSCP 2015\n"
        txt += "=" * 70 + "\n"

        self.results_text.insert(tk.END, txt)

    def generate_report(self):
        if not self.results:
            messagebox.showwarning("⚠️ No Results", "Please run calculation first.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            title="Save PDF Report"
        )
        if filename:
            pdf = PDFGenerator(self.results, filename, self.materials,
                               self.geometry, self.loads, self.design_params)
            pdf.generate()
            messagebox.showinfo("✅ Success", "PDF report generated successfully!")

    def export_dxf(self):
        """Export stairway design to DXF file"""
        if not DXF_AVAILABLE:
            messagebox.showerror(
                "❌ DXF Export Not Available",
                "The ezdxf library is not installed.\n\n"
                "To enable DXF export, please install it using:\n"
                "pip install ezdxf"
            )
            return

        if not self.results:
            messagebox.showwarning("⚠️ No Results", "Please run calculation first.")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
            title="Save DXF Drawing"
        )

        if filename:
            try:
                generator = StairwayDXFGenerator(
                    self.results,
                    self.geometry,
                    self.materials,
                    self.design_params
                )
                generator.create_dxf(filename)
                messagebox.showinfo(
                    "✅ Success",
                    f"DXF drawing generated successfully!\n\n"
                    f"File saved to:\n{filename}\n\n"
                    f"The drawing includes:\n"
                    f"• Section view with reinforcement\n"
                    f"• Plan view with bar layout\n"
                    f"• Reinforcement details\n"
                    f"• Complete dimensions"
                )
            except Exception as e:
                messagebox.showerror("❌ Export Error", f"Failed to generate DXF:\n{str(e)}")

    def clear_results(self):
        self.results_text.delete(1.0, tk.END)
        self.results = {}
        self.results_text.insert(tk.END, "\n\n" + " " * 25 + "No results to display\n" +
                                 " " * 20 + "Click 'Calculate Design' to begin")


# PDF Generator class
class PDFGenerator:
    def __init__(self, results, filename, materials, geometry, loads, design_params):
        self.results = results
        self.filename = filename
        self.materials = materials
        self.geometry = geometry
        self.loads = loads
        self.design_params = design_params
        self.doc = SimpleDocTemplate(self.filename, pagesize=A4)
        self.styles = getSampleStyleSheet()
        self.story = []

    def add_title(self):
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=self.styles['Title'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER
        )
        title = Paragraph("NSCP 2015 CONCRETE STAIRWAY DESIGN REPORT", title_style)
        self.story.append(title)
        self.story.append(Spacer(1, 20))

    def add_project_info(self):
        style = self.styles['Normal']
        date_str = datetime.now().strftime("%B %d, %Y")
        info = (
            f"<b>Project:</b> Concrete Stairway Design<br/>"
            f"<b>Date:</b> {date_str}<br/>"
            f"<b>Code:</b> NSCP 2015<br/>"
            f"<b>Designer:</b> Structural Engineer"
        )
        self.story.append(Paragraph(info, style))
        self.story.append(Spacer(1, 20))

    def add_material_properties(self):
        style = self.styles['Heading2']
        self.story.append(Paragraph("<b>1. MATERIAL PROPERTIES</b>", style))
        m = self.materials
        data = [
            ['Property', 'Value', 'Unit'],
            ['Concrete f\'c', f"{m.fc}", 'MPa'],
            ['Steel fy', f"{m.fy}", 'MPa'],
            ['Concrete γ', f"{m.concrete_unit_weight}", 'kN/m³'],
            ['Beta (β₁)', f"{m.beta1}", '-'],
            ['ρ min', f"{m.rho_min:.6f}", '-'],
            ['ρ max', f"{m.rho_max:.6f}", '-'],
            ['ρ balanced', f"{m.rho_b:.6f}", '-']
        ]
        table = Table(data, colWidths=[2.5 * inch, 1 * inch, 1 * inch])
        table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ])
        self.story.append(Spacer(1, 10))
        self.story.append(table)
        self.story.append(Spacer(1, 20))

    def add_geometry_and_loads(self):
        style = self.styles['Heading2']
        self.story.append(Paragraph("<b>2. GEOMETRY AND LOADS</b>", style))
        g = self.geometry
        l = self.loads
        geom_data = [
            ['Parameter', 'Value', 'Unit'],
            ['Tread Width', f"{g.tread_width}", 'm'],
            ['Riser Height', f"{g.riser_height}", 'm'],
            ['Clear Span', f"{g.clear_span}", 'm'],
            ['Steps - First', f"{g.steps_first_flight}", 'steps'],
            ['Steps - Second', f"{g.steps_second_flight}", 'steps']
        ]
        geom_table = Table(geom_data, colWidths=[2.5 * inch, 1 * inch, 1 * inch])
        geom_table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ])
        self.story.append(geom_table)
        self.story.append(Spacer(1, 15))
        load_data = [
            ['Load Type', 'Value', 'Unit'],
            ['Live Load', f"{l.live_load}", 'kPa'],
            ['Misc Live', f"{l.misc_live_load}", 'kPa'],
            ['Floor Finish', f"{l.floor_finish}", 'kPa'],
            ['Misc Dead', f"{l.misc_dead_load}", 'kPa']
        ]
        load_table = Table(load_data, colWidths=[2.5 * inch, 1 * inch, 1 * inch])
        load_table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ])
        self.story.append(load_table)
        self.story.append(Spacer(1, 15))
        support_info = [
            ['Support Configuration for Design'],
            [f"First Support: {self.results.get('flight1', {}).get('support_config', 'N/A')}"],
        ]
        if 'flight2' in self.results:
            support_info.append([f"Second Support: {self.results.get('flight2', {}).get('support_config', 'N/A')}"])
        support_table = Table(support_info, colWidths=[6 * inch])
        support_table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
        ])
        self.story.append(support_table)
        self.story.append(Spacer(1, 20))

    def add_flight_results(self, flight_key, flight_number):
        f = self.results[flight_key]
        style = self.styles['Heading2']
        self.story.append(Paragraph(f"<b>3.{flight_number} {f['flight_name'].upper()} DESIGN RESULTS</b>", style))
        data = [
            ['Parameter', 'Value'],
            ['Support', f['support_config']],
            ['Min Thickness (mm)', f"{f['h_min']:.1f}"],
            ['Adopted Thickness (mm)', f"{f['slab_thickness']:.1f}"],
            ['Effective Depth (mm)', f"{f['effective_depth']:.1f}"],
            ['Dead Load (kPa)', f"{f['dead_load']:.2f}"],
            ['Live Load (kPa)', f"{f['live_load']:.2f}"],
            ['Factored Load (kPa)', f"{f['factored_load']:.2f}"],
            ['Max Moment (kNm)', f"{f['max_moment']:.2f}"],
            ['Steel Area (mm²)', f"{f['main_steel_area']:.2f}"],
            ['Steel Ratio', f"{f['steel_ratio']:.6f}"],
            ['Main Bar Spacing (mm)', f"{f['main_bar_spacing']:.1f}"],
            ['Temp Steel Area (mm²)', f"{f['temp_steel_area']:.2f}"],
            ['Temp Bar Spacing (mm)', f"{f['temp_bar_spacing']:.1f}"],
        ]
        table = Table(data, colWidths=[3 * inch, 3 * inch])
        table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ])
        self.story.append(table)
        self.story.append(Spacer(1, 15))

    def add_reinforcement(self):
        style = self.styles['Heading2']
        self.story.append(Spacer(1, 20))
        self.story.append(Paragraph("<b>REINFORCEMENT SCHEDULE</b>", style))
        res = self.results
        main_dia_str = f"{int(self.design_params.main_bar_diameter)} mm"
        temp_dia_str = f"{int(self.design_params.temp_bar_diameter)} mm"
        if 'flight1' in res:
            f1 = res['flight1']
            main_spacing_str = f"{int(f1['main_bar_spacing'])} mm"
            temp_spacing_str = f"{int(f1['temp_bar_spacing'])} mm"
            self.story.append(Paragraph(
                f"<b>First Flight:</b><br/>"
                f"  • Main Reinforcement: {main_dia_str} ⌀ @ {main_spacing_str} c/c<br/>"
                f"  • Temperature Bars: {temp_dia_str} ⌀ @ {temp_spacing_str} c/c",
                self.styles['Normal']
            ))
        if 'flight2' in res:
            f2 = res['flight2']
            main_spacing_str = f"{int(f2['main_bar_spacing'])} mm"
            temp_spacing_str = f"{int(f2['temp_bar_spacing'])} mm"
            self.story.append(Paragraph(
                f"<b>Second Flight:</b><br/>"
                f"  • Main Reinforcement: {main_dia_str} ⌀ @ {main_spacing_str} c/c<br/>"
                f"  • Temperature Bars: {temp_dia_str} ⌀ @ {temp_spacing_str} c/c",
                self.styles['Normal']
            ))

    def add_summary(self):
        style = self.styles['Heading2']
        self.story.append(Spacer(1, 20))
        self.story.append(Paragraph("<b>4. DESIGN SUMMARY</b>", style))
        self.story.append(Spacer(1, 10))
        self.story.append(Paragraph(
            "The concrete stairway has been designed in accordance with NSCP 2015 standards, "
            "considering all specified parameters and support configurations. All reinforcement "
            "ratios are within acceptable limits and the design satisfies strength and serviceability requirements.",
            self.styles['Normal']
        ))

    def generate(self):
        self.add_title()
        self.add_project_info()
        self.add_material_properties()
        self.add_geometry_and_loads()
        if 'flight1' in self.results:
            self.add_flight_results('flight1', '1')
        if 'flight2' in self.results:
            self.add_flight_results('flight2', '2')
        self.add_reinforcement()
        self.add_summary()
        self.doc.build(self.story)


def main():
    root = tk.Tk()
    app = ModernStairwayDesigner(root)
    root.mainloop()


if __name__ == "__main__":
    main()