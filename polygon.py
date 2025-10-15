import streamlit as st
import os
import zipfile
import geopandas as gpd
import fiona
from shapely.geometry import LineString
import folium

def generate_turbine_perimeter_from_kmz(kmz_bytes, layer_name, num_points=20, zoom_start=12):
    os.makedirs("tmp_upload", exist_ok=True)
    tmp_kmz_path = "tmp_upload/uploaded.kmz"
    tmp_kml_dir = "tmp_upload/tmp_kml"

    with open(tmp_kmz_path, "wb") as f:
        f.write(kmz_bytes)

    with zipfile.ZipFile(tmp_kmz_path, "r") as z:
        z.extractall(tmp_kml_dir)

    # Find KML file
    kml_path = None
    for file in os.listdir(tmp_kml_dir):
        if file.endswith(".kml"):
            kml_path = os.path.join(tmp_kml_dir, file)
            break
    if not kml_path:
        raise FileNotFoundError("No .kml file found inside KMZ.")

    # Load the specified layer
    gdf = gpd.read_file(kml_path, driver="KML", layer=layer_name)

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # Project to metric CRS (UTM 35S)
    gdf_m = gdf.to_crs("EPSG:32735")

    # Combine and make perimeter
    combined = gdf_m.union_all()
    perimeter = combined.convex_hull

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

    # Add perimeter sample points
    for i, (lon, lat) in enumerate(resampled_coords):
        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color='blue',
            fill=True,
            popup=f"Point {i+1}"
        ).add_to(m)

    # Add centroid marker
    folium.Marker(
        location=center,
        popup=f"Centroid\nLat: {center[0]:.6f}, Lon: {center[1]:.6f}",
        icon=folium.Icon(color='green', icon='star')
    ).add_to(m)

    folium.LayerControl().add_to(m)

    html_bytes = m._repr_html_().encode('utf-8')
    txt_content = (
        "Perimeter Points (longitude, latitude):\n"
        + "\n".join([f"{i+1}: {coord}" for i, coord in enumerate(resampled_coords)])
        + "\n\nCentroid (latitude, longitude):\n"
        + f"{center[0]:.6f}, {center[1]:.6f}"
    )

    return html_bytes, txt_content, center


# ---------------------------------------------------------
# --- Streamlit UI ---
# ---------------------------------------------------------
st.title("💨 Wind Turbine Perimeter Generator")
st.markdown("Upload a KMZ file to generate a polygon around turbine locations.")

uploaded_file = st.file_uploader("Upload KMZ file", type=["kmz"])
num_points = st.slider("Number of perimeter points", 4, 20, 10)

# --- When KMZ is uploaded, show available layers ---
if uploaded_file:
    os.makedirs("tmp_upload", exist_ok=True)
    tmp_kmz_path = "tmp_upload/uploaded.kmz"
    tmp_kml_dir = "tmp_upload/tmp_kml"

    with open(tmp_kmz_path, "wb") as f:
        f.write(uploaded_file.read())

    with zipfile.ZipFile(tmp_kmz_path, "r") as z:
        z.extractall(tmp_kml_dir)

    kml_path = None
    for file in os.listdir(tmp_kml_dir):
        if file.endswith(".kml"):
            kml_path = os.path.join(tmp_kml_dir, file)
            break

    if kml_path:
        layers = fiona.listlayers(kml_path)
        selected_layer = st.selectbox("Select KML layer", layers)

        # --- Generate Perimeter Button ---
        if st.button("Generate Perimeter Map"):
            with st.spinner("Processing..."):
                html_bytes, txt_content, centroid_coords = generate_turbine_perimeter_from_kmz(
                    open(tmp_kmz_path, "rb").read(),
                    layer_name=selected_layer,
                    num_points=num_points,
                )
                st.session_state["map_html"] = html_bytes
                st.session_state["txt_content"] = txt_content
                st.session_state["centroid_coords"] = centroid_coords
                st.success("✅ Perimeter and centroid generated successfully!")


# --- Display map, centroid, and download buttons ---
if "map_html" in st.session_state:
    st.markdown("### 🌍 Perimeter Map")
    st.components.v1.html(st.session_state["map_html"].decode(), height=600)

    st.markdown("### 📍 Centroid of Wind Farm")
    lat, lon = st.session_state["centroid_coords"]
    st.write(f"**Latitude:** {lat:.6f}")
    st.write(f"**Longitude:** {lon:.6f}")

    st.download_button(
        "📥 Download Map (HTML)",
        st.session_state["map_html"],
        file_name="Map.html",
        mime="text/html",
    )

    st.download_button(
        "📥 Download Polygon Points + Centroid (TXT)",
        st.session_state["txt_content"],
        file_name="PolygonPoints.txt",
        mime="text/plain",
    )
