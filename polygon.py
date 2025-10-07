import streamlit as st
import zipfile
import geopandas as gpd
import folium
import os
from shapely.geometry import LineString

# ---------------------------------------------------------
# --- Helper function to extract perimeter from KMZ ---
# ---------------------------------------------------------
def generate_turbine_perimeter_from_kmz(kmz_bytes, num_points=20, buffer_distance=0, zoom_start=12):
    os.makedirs("tmp_upload", exist_ok=True)
    tmp_kmz_path = "tmp_upload/uploaded.kmz"
    tmp_kml_dir = "tmp_upload/tmp_kml"

    with open(tmp_kmz_path, "wb") as f:
        f.write(kmz_bytes)

    with zipfile.ZipFile(tmp_kmz_path, 'r') as z:
        z.extractall(tmp_kml_dir)

    kml_path = None
    for file in os.listdir(tmp_kml_dir):
        if file.endswith(".kml"):
            kml_path = os.path.join(tmp_kml_dir, file)
            break
    if not kml_path:
        raise FileNotFoundError("No .kml file found inside KMZ.")

    gdf = gpd.read_file(kml_path, driver='KML')

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # Project to UTM 35S (metric)
    gdf_m = gdf.to_crs("EPSG:32735")

    # Combine and make perimeter
    combined = gdf_m.union_all()
    perimeter = combined.convex_hull
    if buffer_distance > 0:
        perimeter = perimeter.buffer(buffer_distance)

    # Convert back to WGS84
    perimeter_gdf = gpd.GeoDataFrame(geometry=[perimeter], crs="EPSG:32735").to_crs("EPSG:4326")
    perimeter = perimeter_gdf.geometry.iloc[0]

    # Resample perimeter
    perimeter_line = LineString(perimeter.exterior.coords)
    resampled_points = [
        perimeter_line.interpolate(i / num_points, normalized=True)
        for i in range(num_points)
    ]
    resampled_coords = [(p.x, p.y) for p in resampled_points]

    # Centroid (accurate in metric CRS)
    centroid = gdf_m.geometry.centroid.unary_union.centroid
    centroid_wgs = gpd.GeoSeries([centroid], crs="EPSG:32735").to_crs("EPSG:4326").iloc[0]
    center = [centroid_wgs.y, centroid_wgs.x]

    # Create folium map
    m = folium.Map(location=center, zoom_start=zoom_start)
    folium.GeoJson(gdf.to_crs("EPSG:4326"), name="Turbines").add_to(m)
    folium.GeoJson(
        perimeter,
        name="Perimeter",
        style_function=lambda x: {'color': 'red', 'weight': 2, 'fillOpacity': 0.1}
    ).add_to(m)

    for i, (lon, lat) in enumerate(resampled_coords):
        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color='blue',
            fill=True,
            popup=f"Point {i+1}"
        ).add_to(m)

    folium.LayerControl().add_to(m)

    html_bytes = m._repr_html_().encode('utf-8')
    txt_content = "Perimeter Points (longitude, latitude):\n" + "\n".join(
        [f"{i+1}: {coord}" for i, coord in enumerate(resampled_coords)]
    )

    return html_bytes, txt_content


# ---------------------------------------------------------
# --- Streamlit UI ---
# ---------------------------------------------------------
st.title("Wind Turbine Perimeter Generator")
st.markdown("Upload a KMZ file to generate a polygon around turbine locations.")

uploaded_file = st.file_uploader("Upload KMZ file", type=["kmz"])
num_points = st.slider("Number of perimeter points", 4, 20, 10)
buffer_distance = st.number_input("Buffer distance (meters)", 0, 1000, 0)

# Button to generate
if uploaded_file and st.button("Generate Perimeter Map"):
    with st.spinner("Processing..."):
        html_bytes, txt_content = generate_turbine_perimeter_from_kmz(
            uploaded_file.read(),
            num_points=num_points,
            buffer_distance=buffer_distance
        )
        # Store results in session state
        st.session_state["map_html"] = html_bytes
        st.session_state["txt_content"] = txt_content
        st.success("Perimeter generated successfully!")

# Display map if available
if "map_html" in st.session_state:
    st.markdown("### 🌍 Perimeter Map")
    st.components.v1.html(st.session_state["map_html"].decode(), height=600)

    # Download buttons
    st.download_button(
        "📥 Download Map (HTML)",
        st.session_state["map_html"],
        file_name="SanKraal_WindFarm.html",
        mime="text/html"
    )
    st.download_button(
        "📥 Download Polygon Points (TXT)",
        st.session_state["txt_content"],
        file_name="SanKraal_PolygonPoints.txt",
        mime="text/plain"
    )
