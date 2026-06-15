import { useCallback, useEffect, useRef, useState } from "react";
import { analyzeVisionImage, fetchVisionStatus } from "../ipc/apiClient.js";

// Keep the capture small so on-device vision (Ollama llava) stays responsive on
// modest hardware (e.g. an 8 GB MacBook): a low-res preview stream, a single
// still grabbed on demand, downscaled to a short edge and JPEG-compressed before
// it is sent to the backend. We never stream frames continuously.
const MAX_CAPTURE_EDGE = 512;
const CAPTURE_QUALITY = 0.6;
const VIDEO_CONSTRAINTS = {
  width: { ideal: 640 },
  height: { ideal: 480 },
  frameRate: { ideal: 15 },
};

export function useOdinCamera({ onError } = {}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [previewActive, setPreviewActive] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [available, setAvailable] = useState(false);
  const [description, setDescription] = useState("");
  const [cameraDevices, setCameraDevices] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchVisionStatus()
      .then((status) => {
        if (!cancelled) {
          setAvailable(Boolean(status.configured));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAvailable(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stopPreview = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setPreviewActive(false);
  }, []);

  const refreshCameras = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return;
    }
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
      (device) => device.kind === "videoinput",
    );
    setCameraDevices(devices);
    setSelectedCamera((current) => current || devices[0]?.deviceId || "");
  }, []);

  const startPreview = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      onError?.("Browser camera capture is unavailable.");
      return;
    }
    try {
      if (globalThis.jarvisDesktop?.requestCamera) {
        const allowed = await globalThis.jarvisDesktop.requestCamera();
        if (!allowed) {
          throw new DOMException("Camera access was denied.", "NotAllowedError");
        }
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: selectedCamera
          ? { deviceId: { exact: selectedCamera }, ...VIDEO_CONSTRAINTS }
          : VIDEO_CONSTRAINTS,
      });
      streamRef.current = stream;
      await refreshCameras();
      // The <video> element only mounts once previewActive flips true, so the
      // stream is attached in the effect below (after the element exists) —
      // attaching here would no-op against a null ref and show a blank preview.
      setPreviewActive(true);
    } catch (error) {
      onError?.(
        error?.name === "NotAllowedError"
          ? "Camera access was denied. Allow camera access in system settings, then try again."
          : `Camera could not start: ${error.message}`,
      );
    }
  }, [onError, refreshCameras, selectedCamera]);

  const togglePreview = useCallback(() => {
    if (previewActive) {
      stopPreview();
    } else {
      void startPreview();
    }
  }, [previewActive, startPreview, stopPreview]);

  const captureAndAnalyze = useCallback(
    async (prompt = null) => {
      const video = videoRef.current;
      if (!video || !streamRef.current) {
        onError?.("Start the camera before capturing.");
        return null;
      }
      const sourceWidth = video.videoWidth || 640;
      const sourceHeight = video.videoHeight || 480;
      const scale = Math.min(1, MAX_CAPTURE_EDGE / Math.max(sourceWidth, sourceHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(sourceWidth * scale));
      canvas.height = Math.max(1, Math.round(sourceHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) {
        onError?.("Image capture is unavailable in this environment.");
        return null;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", CAPTURE_QUALITY);
      const imageBase64 = dataUrl.split(",")[1] || "";
      if (!imageBase64) {
        onError?.("Camera frame could not be captured.");
        return null;
      }
      setAnalyzing(true);
      try {
        const response = await analyzeVisionImage({
          imageBase64,
          imageSuffix: ".jpg",
          prompt,
        });
        setDescription(response.description);
        return response.description;
      } catch (error) {
        onError?.(`Vision analysis failed: ${error.message}`);
        return null;
      } finally {
        setAnalyzing(false);
      }
    },
    [onError],
  );

  // Attach the live stream once the <video> has actually mounted (it only
  // renders while previewActive is true). Running here — not inside
  // startPreview — guarantees videoRef points at a real element.
  useEffect(() => {
    const video = videoRef.current;
    if (!previewActive || !video || !streamRef.current) {
      return;
    }
    if (video.srcObject !== streamRef.current) {
      video.srcObject = streamRef.current;
    }
    video.play?.().catch(() => {});
  }, [previewActive]);

  useEffect(() => stopPreview, [stopPreview]);

  return {
    videoRef,
    previewActive,
    analyzing,
    available,
    description,
    cameraDevices,
    selectedCamera,
    setSelectedCamera,
    startPreview,
    stopPreview,
    togglePreview,
    captureAndAnalyze,
  };
}
