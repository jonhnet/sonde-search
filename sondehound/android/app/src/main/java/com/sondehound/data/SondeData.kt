package com.sondehound.data

import org.osmdroid.util.GeoPoint

/**
 * A single position report from a radiosonde.
 */
data class SondePosition(
    val latitude: Double,
    val longitude: Double,
    val altitude: Double,       // meters
    val timestamp: Long,        // epoch seconds
    val speed: Double = 0.0,    // m/s ground speed
    val heading: Double = 0.0,  // degrees
    val climbRate: Double = 0.0 // m/s, negative = descending
) {
    fun toGeoPoint(): GeoPoint = GeoPoint(latitude, longitude, altitude)
}

/**
 * Predicted landing position from auto_rx's built-in predictor.
 */
data class LandingPrediction(
    val latitude: Double,
    val longitude: Double,
    val timestamp: Long
) {
    fun toGeoPoint(): GeoPoint = GeoPoint(latitude, longitude)
}

/**
 * Represents a single radiosonde being tracked.
 */
data class Sonde(
    val serial: String,
    val type: String,           // e.g. "RS41", "DFM", "M10"
    val frequency: Double,      // MHz
    val positions: MutableList<SondePosition> = mutableListOf(),
    var landingPrediction: LandingPrediction? = null,
    var predictedPath: List<SondePosition>? = null,
    var snr: Double = 0.0       // signal-to-noise ratio
) {
    val latestPosition: SondePosition?
        get() = positions.lastOrNull()

    val isDescending: Boolean
        get() = latestPosition?.climbRate?.let { it < -0.5 } ?: false
}

/**
 * Operating mode for the receiver.
 */
enum class ReceiverMode {
    AUTO,       // auto_rx scans and locks onto any sonde it finds
    FREQUENCY   // user specifies a single frequency to monitor
}

/**
 * Overall state of the receiver connection and tracked sondes.
 */
data class ReceiverState(
    val connected: Boolean = false,
    val mode: ReceiverMode = ReceiverMode.AUTO,
    val selectedFrequency: Double? = null, // MHz, only used in FREQUENCY mode
    val sondes: Map<String, Sonde> = emptyMap()
)
