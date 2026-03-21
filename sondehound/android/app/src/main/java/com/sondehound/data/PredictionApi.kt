package com.sondehound.data

import android.util.Log
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/**
 * Client for the CUSF/Tawhiri landing prediction API hosted by SondeHub.
 *
 * Sends the sonde's current position and descent rate to the API and
 * receives back a predicted descent path to the ground.
 */
object PredictionApi {

    private const val TAG = "PredictionApi"
    private const val BASE_URL = "https://api.v2.sondehub.org/tawhiri"
    private const val MIN_REQUEST_INTERVAL_MS = 30_000L
    private const val MIN_ALTITUDE_M = 500.0 // don't predict below this
    private const val DEFAULT_BURST_ALTITUDE = 30000.0 // meters, typical for RS41
    private const val DEFAULT_DESCENT_RATE = 5.0 // m/s terminal velocity at sea level

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()
    private var lastRequestTime = mutableMapOf<String, Long>()
    private var job: Job? = null

    /**
     * Ensure the periodic prediction loop is running.
     * Safe to call repeatedly — only starts the loop once.
     */
    fun ensureRunning() {
        if (job?.isActive == true) return
        job = CoroutineScope(Dispatchers.IO).launch {
            while (isActive) {
                val state = SondeRepository.receiverState.value
                state?.sondes?.forEach { (serial, sonde) ->
                    val pos = sonde.latestPosition ?: return@forEach
                    if (pos.altitude < MIN_ALTITUDE_M) return@forEach

                    val now = System.currentTimeMillis()
                    val lastReq = lastRequestTime[serial] ?: 0
                    if (now - lastReq < MIN_REQUEST_INTERVAL_MS) return@forEach

                    lastRequestTime[serial] = now
                    try {
                        val prediction = if (sonde.isDescending) {
                            // Descending: predict from current position straight down
                            fetchPrediction(
                                lat = pos.latitude,
                                lon = pos.longitude,
                                alt = pos.altitude,
                                ascentRate = 5.0, // ignored, burst is immediate
                                burstAltitude = pos.altitude + 1.0,
                                descentRate = abs(pos.climbRate).coerceAtLeast(1.0)
                            )
                        } else {
                            // Ascending: predict full remaining ascent + burst + descent
                            fetchPrediction(
                                lat = pos.latitude,
                                lon = pos.longitude,
                                alt = pos.altitude,
                                ascentRate = pos.climbRate.coerceAtLeast(1.0),
                                burstAltitude = DEFAULT_BURST_ALTITUDE.coerceAtLeast(pos.altitude + 100.0),
                                descentRate = DEFAULT_DESCENT_RATE
                            )
                        }
                        if (prediction != null) {
                            SondeRepository.updatePrediction(serial, prediction)
                            Log.i(TAG, "$serial: predicted landing at " +
                                "(${prediction.landingPoint.latitude}, " +
                                "${prediction.landingPoint.longitude})")
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "$serial: prediction failed: ${e.message}")
                    }
                }
                delay(5000) // check every 5 seconds, but per-sonde rate-limited
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        lastRequestTime.clear()
    }

    /**
     * Fetch a prediction from the Tawhiri API.
     *
     * For descent-only: set burstAltitude = current alt + 1.
     * For full flight: set real ascentRate, estimated burstAltitude, and descentRate.
     */
    private fun fetchPrediction(
        lat: Double,
        lon: Double,
        alt: Double,
        ascentRate: Double,
        burstAltitude: Double,
        descentRate: Double
    ): DescentPrediction? {
        // API requires longitude in 0-360 range
        val apiLon = if (lon < 0) lon + 360.0 else lon

        val url = BASE_URL.toHttpUrl().newBuilder()
            .addQueryParameter("launch_latitude", "%.6f".format(lat))
            .addQueryParameter("launch_longitude", "%.6f".format(apiLon))
            .addQueryParameter("launch_altitude", "%.1f".format(alt))
            .addQueryParameter("launch_datetime",
                DateTimeFormatter.ISO_INSTANT.format(Instant.now()))
            .addQueryParameter("ascent_rate", "%.1f".format(ascentRate))
            .addQueryParameter("burst_altitude", "%.1f".format(burstAltitude))
            .addQueryParameter("descent_rate", "%.1f".format(descentRate))
            .build()

        Log.d(TAG, "Requesting prediction: $url")

        val request = Request.Builder().url(url).build()
        val response = client.newCall(request).execute()

        if (!response.isSuccessful) {
            val body = response.body?.string() ?: ""
            Log.w(TAG, "API error ${response.code}: $body")
            return null
        }

        val body = response.body?.string() ?: return null
        val apiResponse = gson.fromJson(body, TawhiriResponse::class.java)

        // Combine all stages (ascent + descent) into one path
        val path = apiResponse.prediction.flatMap { stage ->
            stage.trajectory.map { point ->
                // Convert longitude back from 0-360 to -180/+180
                val pointLon = if (point.longitude > 180) point.longitude - 360.0 else point.longitude
                SondePosition(
                    latitude = point.latitude,
                    longitude = pointLon,
                    altitude = point.altitude,
                    timestamp = 0
                )
            }
        }

        if (path.isEmpty()) return null

        val landing = path.last()
        return DescentPrediction(
            path = path,
            landingPoint = LandingPrediction(
                latitude = landing.latitude,
                longitude = landing.longitude,
                timestamp = System.currentTimeMillis() / 1000
            )
        )
    }
}

/**
 * A complete descent prediction: the path and the landing point.
 */
data class DescentPrediction(
    val path: List<SondePosition>,
    val landingPoint: LandingPrediction
)

// --- Tawhiri API response models ---

data class TawhiriResponse(
    val prediction: List<PredictionStage>
)

data class PredictionStage(
    val stage: String,
    val trajectory: List<TrajectoryPoint>
)

data class TrajectoryPoint(
    val latitude: Double,
    val longitude: Double,
    val altitude: Double,
    val datetime: String
)
