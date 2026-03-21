package com.sondehound.data

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData

/**
 * Central repository for all sonde tracking state.
 * Updated by BleService when new telemetry arrives.
 *
 * All mutations go through a synchronized lock to avoid races between
 * the BLE callback thread, IO dispatcher, and main thread.
 */
object SondeRepository {

    private val lock = Object()
    private val _receiverState = MutableLiveData(ReceiverState())
    val receiverState: LiveData<ReceiverState> = _receiverState

    private val _connectionStatus = MutableLiveData("Disconnected")
    val connectionStatus: LiveData<String> = _connectionStatus

    fun updateConnectionStatus(status: String) {
        _connectionStatus.postValue(status)
    }

    fun setConnected(connected: Boolean) {
        synchronized(lock) {
            val current = _receiverState.value ?: ReceiverState()
            _receiverState.postValue(current.copy(
                connected = connected,
                sondes = HashMap(current.sondes)
            ))
        }
    }

    fun setMode(mode: ReceiverMode, frequency: Double? = null) {
        synchronized(lock) {
            val current = _receiverState.value ?: ReceiverState()
            _receiverState.postValue(current.copy(
                mode = mode,
                selectedFrequency = frequency,
                sondes = HashMap(current.sondes)
            ))
        }
    }

    fun handleAutoRxMessage(msg: AutoRxMessage) {
        synchronized(lock) {
            val current = _receiverState.value ?: ReceiverState()

            // Deep copy the sondes map so observers get a fresh object
            val newSondes = HashMap(current.sondes)
            val existing = newSondes[msg.callsign]
            val sonde = if (existing != null) {
                existing.copy(
                    positions = ArrayList(existing.positions),
                    predictedPath = existing.predictedPath?.let { ArrayList(it) }
                )
            } else {
                Sonde(
                    serial = msg.callsign,
                    type = msg.model,
                    frequency = msg.parseFrequencyMhz()
                )
            }

            val position = msg.toSondePosition()
            sonde.positions.add(position)
            sonde.snr = msg.snr
            newSondes[msg.callsign] = sonde

            _receiverState.postValue(current.copy(sondes = newSondes))
        }

        // Start prediction updates whenever we have sonde data
        PredictionApi.ensureRunning()
    }

    fun updatePrediction(serial: String, prediction: DescentPrediction) {
        synchronized(lock) {
            val current = _receiverState.value ?: ReceiverState()
            val existing = current.sondes[serial] ?: return
            val newSondes = HashMap(current.sondes)
            val sonde = existing.copy(
                positions = ArrayList(existing.positions),
                landingPrediction = prediction.landingPoint,
                predictedPath = prediction.path
            )
            newSondes[serial] = sonde
            _receiverState.postValue(current.copy(sondes = newSondes))
        }
    }

    fun clear() {
        synchronized(lock) {
            _receiverState.postValue(ReceiverState())
        }
    }
}
