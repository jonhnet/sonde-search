package com.sondehound.ui

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.location.Location
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.location.*
import com.sondehound.BuildConfig
import com.sondehound.R
import com.sondehound.ble.BleService
import com.sondehound.data.MockDataSource
import com.sondehound.data.ReceiverMode
import com.sondehound.data.Sonde
import com.sondehound.data.SondeRepository
import com.sondehound.databinding.ActivityMapBinding
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline

class MapActivity : AppCompatActivity() {

    companion object {
        private const val PERMISSION_REQUEST_CODE = 1001

        private val REQUIRED_PERMISSIONS: Array<String>
            get() = when {
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT,
                    Manifest.permission.POST_NOTIFICATIONS
                )
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT
                )
                else -> arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION
                )
            }
    }

    private lateinit var binding: ActivityMapBinding
    private lateinit var map: MapView
    private lateinit var fusedLocationClient: FusedLocationProviderClient

    private var bleService: BleService? = null
    private var serviceBound = false

    // Map overlays we manage
    private var userMarker: Marker? = null
    private val sondeMarkers = mutableMapOf<String, Marker>()
    private val sondePolylines = mutableMapOf<String, Polyline>()
    private val predictionPolylines = mutableMapOf<String, Polyline>()
    private val landingMarkers = mutableMapOf<String, Marker>()
    private var bearingLine: Polyline? = null

    // Current user location
    private var userLocation: Location? = null

    // Which sonde is currently selected for bearing display
    private var selectedSondeSerial: String? = null

    // Staleness timer
    private val stalenessHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val stalenessRunnable = object : Runnable {
        override fun run() {
            val state = SondeRepository.receiverState.value
            if (state != null && state.sondes.isNotEmpty()) {
                updateSondeList(state.sondes)
            }
            stalenessHandler.postDelayed(this, 1000)
        }
    }

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            bleService = (service as BleService.LocalBinder).getService()
            serviceBound = true
            bleService?.startScanning()
        }

        override fun onServiceDisconnected(name: ComponentName) {
            bleService = null
            serviceBound = false
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMapBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupMap()
        setupUI()
        setupLocationUpdates()
        observeData()

        if (hasAllPermissions()) {
            startBleService()
        } else {
            requestPermissions()
        }
    }

    private fun setupMap() {
        map = binding.mapView
        map.setTileSource(TileSourceFactory.MAPNIK)
        map.setMultiTouchControls(true)
        map.controller.setZoom(10.0)

    }

    private fun setupUI() {
        // Mode selector
        val modeSpinner = binding.modeSpinner
        val modes = arrayOf("Auto", "Frequency")
        modeSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, modes)
        modeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                val freqLayout = binding.frequencyLayout
                if (pos == 1) {
                    freqLayout.visibility = View.VISIBLE
                } else {
                    freqLayout.visibility = View.GONE
                    bleService?.sendModeCommand(ReceiverMode.AUTO)
                    SondeRepository.setMode(ReceiverMode.AUTO)
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        // Frequency submit
        binding.freqSubmitButton.setOnClickListener {
            val freqStr = binding.freqEditText.text.toString()
            val freq = freqStr.toDoubleOrNull()
            if (freq != null && freq in 400.0..406.0) {
                bleService?.sendModeCommand(ReceiverMode.FREQUENCY, freq)
                SondeRepository.setMode(ReceiverMode.FREQUENCY, freq)
            } else {
                Toast.makeText(this, "Enter frequency 400-406 MHz", Toast.LENGTH_SHORT).show()
            }
        }

        // Mock data button (only visible in debug builds)
        if (BuildConfig.DEBUG) {
            binding.mockButton.visibility = View.VISIBLE
        } else {
            binding.mockButton.visibility = View.GONE
        }
        binding.mockButton.setOnClickListener {
            if (MockDataSource.isRunning()) {
                MockDataSource.stop()
                binding.mockButton.text = "Mock"
            } else {
                MockDataSource.start()
                binding.mockButton.text = "Stop Mock"
                // Center map on the mock sonde's starting area
                map.controller.setZoom(11.0)
                map.controller.animateTo(GeoPoint(40.05, -105.25))
            }
        }

        // Center on user button
        binding.centerUserButton.setOnClickListener {
            userLocation?.let { loc ->
                map.controller.animateTo(GeoPoint(loc.latitude, loc.longitude))
            }
        }

        // Center on sonde button
        binding.centerSondeButton.setOnClickListener {
            val state = SondeRepository.receiverState.value
            if (state == null || state.sondes.isEmpty()) {
                Toast.makeText(this, "No balloons tracked", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val serial = selectedSondeSerial ?: state.sondes.keys.firstOrNull() ?: return@setOnClickListener
            state.sondes[serial]?.latestPosition?.let { pos ->
                map.controller.animateTo(pos.toGeoPoint())
            }
        }
    }

    private fun setupLocationUpdates() {
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)

        val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 2000)
            .setMinUpdateIntervalMillis(1000)
            .build()

        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED) {
            fusedLocationClient.requestLocationUpdates(locationRequest, locationCallback, mainLooper)
        }
    }

    private var hasInitialFix = false

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            result.lastLocation?.let { location ->
                userLocation = location
                updateUserMarker(location)
                updateBearingLine()
                if (!hasInitialFix) {
                    hasInitialFix = true
                    map.controller.setZoom(10.0)
                    map.controller.setCenter(GeoPoint(location.latitude, location.longitude))
                }
            }
        }
    }

    private fun observeData() {
        SondeRepository.receiverState.observe(this) { state ->
            updateSondeOverlays(state.sondes)
            updateSondeList(state.sondes)
            updateBearingLine()
        }

        SondeRepository.connectionStatus.observe(this) { status ->
            // Update bottom panel if no sondes are being tracked
            val state = SondeRepository.receiverState.value
            if (state == null || state.sondes.isEmpty()) {
                binding.sondeListText.text = status
            }
        }
    }

    // -- Map overlay updates --

    private fun updateUserMarker(location: Location) {
        if (userMarker == null) {
            userMarker = Marker(map).apply {
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                title = "You"
                icon = ContextCompat.getDrawable(this@MapActivity, R.drawable.ic_user_location)
            }
            map.overlays.add(userMarker)
        }
        userMarker?.position = GeoPoint(location.latitude, location.longitude)
        map.invalidate()
    }

    private fun updateSondeOverlays(sondes: Map<String, Sonde>) {
        for ((serial, sonde) in sondes) {
            val latest = sonde.latestPosition ?: continue

            // Update or create sonde marker
            val marker = sondeMarkers.getOrPut(serial) {
                Marker(map).apply {
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                    icon = ContextCompat.getDrawable(this@MapActivity, R.drawable.ic_sonde)
                    map.overlays.add(this)
                }
            }
            marker.position = latest.toGeoPoint()
            marker.title = "${sonde.type} $serial"
            marker.snippet = String.format(
                "Alt: %.0fm | %.1fm/s | SNR: %.1f",
                latest.altitude, latest.climbRate, sonde.snr
            )
            marker.setOnMarkerClickListener { _, _ ->
                selectedSondeSerial = serial
                updateBearingLine()
                true
            }

            // Update or create track polyline
            val polyline = sondePolylines.getOrPut(serial) {
                Polyline(map).apply {
                    outlinePaint.color = Color.RED
                    outlinePaint.strokeWidth = 4f
                    map.overlays.add(this)
                }
            }
            polyline.setPoints(sonde.positions.map { it.toGeoPoint() })

            // Update or create predicted descent path polyline
            sonde.predictedPath?.let { path ->
                val predLine = predictionPolylines.getOrPut(serial) {
                    Polyline(map).apply {
                        outlinePaint.color = Color.MAGENTA
                        outlinePaint.strokeWidth = 3f
                        outlinePaint.pathEffect = android.graphics.DashPathEffect(
                            floatArrayOf(15f, 10f), 0f
                        )
                        map.overlays.add(this)
                    }
                }
                predLine.setPoints(path.map { it.toGeoPoint() })
            }

            // Update or create landing prediction marker
            sonde.landingPrediction?.let { pred ->
                val landMarker = landingMarkers.getOrPut(serial) {
                    Marker(map).apply {
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                        icon = ContextCompat.getDrawable(this@MapActivity, R.drawable.ic_landing)
                        title = "Predicted Landing"
                        map.overlays.add(this)
                    }
                }
                landMarker.position = pred.toGeoPoint()
            }
        }

        // Remove overlays for sondes no longer being tracked
        val staleSerials = sondeMarkers.keys - sondes.keys
        for (serial in staleSerials) {
            sondeMarkers.remove(serial)?.let { map.overlays.remove(it) }
            sondePolylines.remove(serial)?.let { map.overlays.remove(it) }
            predictionPolylines.remove(serial)?.let { map.overlays.remove(it) }
            landingMarkers.remove(serial)?.let { map.overlays.remove(it) }
        }

        map.invalidate()
    }

    private fun updateBearingLine() {
        val loc = userLocation ?: return
        val state = SondeRepository.receiverState.value ?: return
        val serial = selectedSondeSerial ?: state.sondes.keys.firstOrNull() ?: return
        val sondePos = state.sondes[serial]?.latestPosition ?: return

        // Remove old bearing line
        bearingLine?.let { map.overlays.remove(it) }

        // Draw new bearing line
        val userGeo = GeoPoint(loc.latitude, loc.longitude)
        val sondeGeo = sondePos.toGeoPoint()
        bearingLine = Polyline(map).apply {
            outlinePaint.color = Color.BLUE
            outlinePaint.strokeWidth = 3f
            outlinePaint.pathEffect = android.graphics.DashPathEffect(floatArrayOf(20f, 10f), 0f)
            setPoints(listOf(userGeo, sondeGeo))
        }
        map.overlays.add(bearingLine)

        map.invalidate()
    }

    private fun updateSondeList(sondes: Map<String, Sonde>) {
        if (sondes.isEmpty()) {
            // Show whatever the current connection status is
            val status = SondeRepository.connectionStatus.value
            if (status != null) {
                binding.sondeListText.text = status
            }
            return
        }
        val sb = StringBuilder()
        for ((serial, sonde) in sondes) {
            val pos = sonde.latestPosition
            val selected = if (serial == selectedSondeSerial) "▸" else ""
            sb.append("${selected}$serial")
            if (pos != null) {
                sb.append(" | %,dm | %.1fm/s".format(pos.altitude.toLong(), pos.climbRate))
                // Add bearing/distance if we have user location
                userLocation?.let { loc ->
                    val results = FloatArray(2)
                    Location.distanceBetween(
                        loc.latitude, loc.longitude,
                        pos.latitude, pos.longitude, results
                    )
                    val distKm = results[0] / 1000.0
                    val brg = if (results[1] < 0) results[1] + 360 else results[1]
                    sb.append(String.format(" | %.1fkm@%.0f°", distKm, brg))
                }
                // Staleness indicator
                val ageSec = System.currentTimeMillis() / 1000 - pos.timestamp
                sb.append(" | ${formatAge(ageSec)}")
            }
            sb.append("\n")
        }
        binding.sondeListText.text = sb.toString().trimEnd()
    }

    private fun formatAge(seconds: Long): String {
        return when {
            seconds < 60 -> "${seconds}s"
            seconds < 3600 -> "${seconds / 60}m"
            else -> "${seconds / 3600}h"
        }
    }

    // -- Permissions --

    private fun hasAllPermissions(): Boolean {
        return REQUIRED_PERMISSIONS.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestPermissions() {
        ActivityCompat.requestPermissions(this, REQUIRED_PERMISSIONS, PERMISSION_REQUEST_CODE)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            startBleService()
            setupLocationUpdates()
        } else {
            Toast.makeText(this, "Permissions required for BLE and GPS", Toast.LENGTH_LONG).show()
        }
    }

    // -- Service lifecycle --

    private fun startBleService() {
        val intent = Intent(this, BleService::class.java)
        startForegroundService(intent)
        bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE)
    }

    override fun onResume() {
        super.onResume()
        map.onResume()
        stalenessHandler.post(stalenessRunnable)
    }

    override fun onPause() {
        super.onPause()
        map.onPause()
        stalenessHandler.removeCallbacks(stalenessRunnable)
    }

    override fun onDestroy() {
        stalenessHandler.removeCallbacksAndMessages(null)
        fusedLocationClient.removeLocationUpdates(locationCallback)
        if (serviceBound) {
            unbindService(serviceConnection)
            serviceBound = false
        }
        super.onDestroy()
    }
}
